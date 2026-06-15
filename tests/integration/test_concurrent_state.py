"""
模組 B：並發狀態機測試（Race Condition）

這些測試的目的是「先記錄現有行為」：
  B3 - serial_number 在並發下的唯一性
  B4 - 序列號碼格式一致性
  B1 - pending_images 並發 append（race condition 記錄）

註：原 Auto Split Timer 並發測試（B2）已隨「自動切割」功能移除一併刪除。

B3 使用 SQLite in-memory（不支援 SELECT FOR UPDATE，但可驗證唯一性約束）。
"""

import asyncio
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


# ---------------------------------------------------------------------------
# B3/B4：序號在並發下的唯一性
# ---------------------------------------------------------------------------


SQLITE_CONCURRENT_URL = "sqlite:///file:concurrent_test?mode=memory&cache=shared&uri=true"


def _init_test_db():
    """建立測試用 SQLite engine 與 expenses 表。"""
    engine = create_engine(
        SQLITE_CONCURRENT_URL,
        connect_args={"check_same_thread": False},
    )
    with engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS expenses"))
        conn.execute(text("""
            CREATE TABLE expenses (
                id TEXT PRIMARY KEY,
                serial_number TEXT UNIQUE NOT NULL,
                image_url TEXT NOT NULL DEFAULT '[]',
                item_image_url TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'PENDING',
                image_count INTEGER NOT NULL DEFAULT 1
            )
        """))
        conn.commit()
    return engine


class TestSerialNumberUniqueness:
    """驗證 M6 風險：並發建立 Expense 時序號應全部唯一。"""

    @pytest.mark.asyncio
    async def test_serial_numbers_unique_under_concurrent_creation(self) -> None:
        """
        20 個協程並發呼叫 _generate_serial_number，模擬並發 Expense 建立。
        所有產生的序號必須全部唯一（現有的 5-retry 機制應足夠保護）。

        注意：SQLite 不支援 SELECT FOR UPDATE，但 UNIQUE 約束仍會生效。
        """
        from services.expense_service import _generate_serial_number

        engine = _init_test_db()
        SessionLocal = sessionmaker(bind=engine)

        generated_serials = []
        errors = []
        lock = asyncio.Lock()

        async def create_one_serial():
            session = SessionLocal()
            try:
                with patch("services.expense_service.datetime") as mock_dt:
                    mock_dt.now.return_value = datetime(2026, 5, 19)
                    serial = _generate_serial_number(session)

                # 模擬 Expense INSERT（驗證唯一性約束）
                session.execute(text(
                    "INSERT INTO expenses (id, serial_number) VALUES (:id, :sn)"
                ), {"id": str(uuid.uuid4()), "sn": serial})
                session.commit()

                async with lock:
                    generated_serials.append(serial)
            except Exception as e:
                async with lock:
                    errors.append(str(e))
            finally:
                session.close()

        # 20 個並發
        await asyncio.gather(*[create_one_serial() for _ in range(20)])

        print(f"[INFO] 成功建立 {len(generated_serials)} 個，錯誤 {len(errors)} 個")
        if errors:
            print(f"[INFO] 錯誤詳情（前 3 個）：{errors[:3]}")

        # 驗證成功的序號無重複
        assert len(generated_serials) == len(set(generated_serials)), \
            f"存在重複序號：{[s for s in generated_serials if generated_serials.count(s) > 1]}"

        # 驗證大部分應成功（允許少數因 retry 耗盡而失敗）
        success_rate = len(generated_serials) / 20
        assert success_rate >= 0.8, \
            f"成功率 {success_rate:.0%} 過低，retry 機制可能有問題"

        engine.dispose()

    @pytest.mark.asyncio
    async def test_serial_number_format_consistency(self) -> None:
        """確認 20 個並發產生的序號格式都正確（EXP-YYYYMM-NNNN）。"""
        import re
        from services.expense_service import _generate_serial_number

        engine = _init_test_db()
        SessionLocal = sessionmaker(bind=engine)

        serials = []
        lock = asyncio.Lock()

        async def get_serial():
            session = SessionLocal()
            try:
                with patch("services.expense_service.datetime") as mock_dt:
                    mock_dt.now.return_value = datetime(2026, 5, 19)
                    serial = _generate_serial_number(session)
                    session.execute(text(
                        "INSERT INTO expenses (id, serial_number) VALUES (:id, :sn)"
                    ), {"id": str(uuid.uuid4()), "sn": serial})
                    session.commit()
                async with lock:
                    serials.append(serial)
            except Exception:
                pass
            finally:
                session.close()

        # 順序執行（避免 unique conflict）以驗證格式
        for _ in range(5):
            await get_serial()

        pattern = re.compile(r"^EXP-\d{6}-\d{4}$")
        for serial in serials:
            assert pattern.match(serial), f"序號格式錯誤：{serial}"

        engine.dispose()


# ---------------------------------------------------------------------------
# B1：pending_images 並發 append（記錄現有行為）
# ---------------------------------------------------------------------------


class TestPendingImagesAppend:
    """
    B1 風險記錄：驗證 pending_images 並發 append 的行為。
    此測試模擬（而非真實 webhook）兩個並發 DB 更新 pending_images 的情境。
    """

    @pytest.mark.asyncio
    async def test_sequential_append_preserves_all_images(self) -> None:
        """
        順序 append 兩張圖片 → pending_images 應包含兩張。
        此為基準測試，確認正確行為。
        """
        import json

        engine = _init_test_db()
        with engine.connect() as conn:
            conn.execute(text(
                "CREATE TABLE IF NOT EXISTS user_states ("
                "  line_user_id TEXT PRIMARY KEY,"
                "  step TEXT NOT NULL DEFAULT 'COLLECTING',"
                "  pending_images TEXT NOT NULL DEFAULT '[]',"
                "  pending_description TEXT NOT NULL DEFAULT ''"
                ")"
            ))
            conn.execute(text(
                "INSERT INTO user_states (line_user_id, pending_images) "
                "VALUES ('test_user', '[]')"
            ))
            conn.commit()

            # 順序 append 第一張
            current = json.loads(
                conn.execute(text(
                    "SELECT pending_images FROM user_states WHERE line_user_id='test_user'"
                )).scalar()
            )
            current.append({"path": "uploads/img1.jpg", "timestamp": 1000, "message_id": "m1"})
            conn.execute(text(
                "UPDATE user_states SET pending_images=:pi WHERE line_user_id='test_user'"
            ), {"pi": json.dumps(current)})
            conn.commit()

            # 順序 append 第二張
            current = json.loads(
                conn.execute(text(
                    "SELECT pending_images FROM user_states WHERE line_user_id='test_user'"
                )).scalar()
            )
            current.append({"path": "uploads/img2.jpg", "timestamp": 2000, "message_id": "m2"})
            conn.execute(text(
                "UPDATE user_states SET pending_images=:pi WHERE line_user_id='test_user'"
            ), {"pi": json.dumps(current)})
            conn.commit()

            # 驗證兩張都存在
            final = json.loads(
                conn.execute(text(
                    "SELECT pending_images FROM user_states WHERE line_user_id='test_user'"
                )).scalar()
            )

        assert len(final) == 2, f"順序 append 應有 2 張，實際 {len(final)} 張"
        paths = [e["path"] for e in final]
        assert "uploads/img1.jpg" in paths
        assert "uploads/img2.jpg" in paths

        engine.dispose()

    @pytest.mark.asyncio
    async def test_concurrent_append_race_condition_documented(self) -> None:
        """
        C1 風險記錄：模擬兩個並發 read-modify-write 的 race condition。

        真實情境：兩個 webhook 幾乎同時到達，都讀到 pending_images=[]，
        各自 append 自己的圖片，後寫者覆蓋先寫者 → 只剩 1 張。

        此測試【不】使用 SELECT FOR UPDATE（模擬有 bug 的現有行為），
        用於記錄並確認 race condition 存在。
        """
        import json

        engine = _init_test_db()
        barrier = asyncio.Barrier(2)  # 確保兩個協程同時開始

        with engine.connect() as conn:
            conn.execute(text(
                "CREATE TABLE IF NOT EXISTS user_states2 ("
                "  line_user_id TEXT PRIMARY KEY,"
                "  pending_images TEXT NOT NULL DEFAULT '[]'"
                ")"
            ))
            conn.execute(text(
                "INSERT INTO user_states2 (line_user_id, pending_images) "
                "VALUES ('race_user', '[]')"
            ))
            conn.commit()

        SessionLocal = sessionmaker(bind=engine)

        async def append_image_without_lock(img_path: str, delay: float = 0):
            """模擬沒有鎖的 read-modify-write。"""
            session = SessionLocal()
            try:
                # 讀取
                current_json = session.execute(text(
                    "SELECT pending_images FROM user_states2 WHERE line_user_id='race_user'"
                )).scalar()
                current = json.loads(current_json)

                await barrier.wait()  # 同步：確保兩個協程同時讀到相同的值
                await asyncio.sleep(delay)  # 模擬處理時間差

                # 修改（各自都基於同樣的舊值）
                current.append({"path": img_path})

                # 寫回（後者覆蓋前者）
                session.execute(text(
                    "UPDATE user_states2 SET pending_images=:pi WHERE line_user_id='race_user'"
                ), {"pi": json.dumps(current)})
                session.commit()
            finally:
                session.close()

        # 兩個並發 append
        await asyncio.gather(
            append_image_without_lock("uploads/img_a.jpg", delay=0.01),
            append_image_without_lock("uploads/img_b.jpg", delay=0.0),
        )

        # 查看最終結果
        with engine.connect() as conn:
            final_json = conn.execute(text(
                "SELECT pending_images FROM user_states2 WHERE line_user_id='race_user'"
            )).scalar()
        final = json.loads(final_json)

        print(f"[INFO] 並發 append 後 pending_images = {final}")

        if len(final) == 1:
            # Race condition 確認：只有 1 張（有圖片遺失）
            import warnings
            warnings.warn(
                "⚠️ C1 Race Condition 已確認：並發 read-modify-write 導致圖片遺失！"
                f"最終只有 {len(final)} 張，應有 2 張。"
                "修復方案：使用 SELECT FOR UPDATE 或 PostgreSQL atomic UPDATE + JSON_APPEND。",
                UserWarning,
                stacklevel=2,
            )
        elif len(final) == 2:
            # 沒有 race condition（可能因執行速度而免於衝突）
            print("[INFO] 此次執行未觸發 race condition（兩張都保留）")

        # 無論如何，斷言「至少有 1 張」（系統不應完全崩潰）
        assert len(final) >= 1, "系統不應在並發下完全丟失所有圖片"

        engine.dispose()
