import duckdb
import polars as pl
import numpy as np
from datetime import datetime, timedelta

conn = duckdb.connect(database=":memory:")

conn.execute("""
CREATE SEQUENCE IF NOT EXISTS pilot_ids START 1;
""")

conn.execute("""
CREATE TABLE Pilots (
    PilotID INTEGER PRIMARY KEY DEFAULT nextval('pilot_ids'),
    UpdateTime TIMESTAMP,
    Status ENUM('Running', 'Waiting', 'Done', 'Failed')
);
""")

conn.execute("""
CREATE TABLE PilotAttributes (
    PilotID INTEGER PRIMARY KEY,
    Cores USMALLINT,
    MemoryMB UINTEGER,
    FOREIGN KEY (PilotID) REFERENCES Pilots(PilotID)
);
""")

start_date = datetime.now() - timedelta(days=90)
end_date = datetime.now()

NUM_PILOTS = 1_000_000

day_weights = np.array([0.01] * 60 + [0.02] * 20 + [0.03] * 10)
day_weights = day_weights / day_weights.sum()
status_weights = np.array([0.5, 0.1, 0.39, 0.01])
status_weights = status_weights / status_weights.sum()
core_weights = np.array([0.6, 0.1, 0.25, 0.05])
core_weights = core_weights / core_weights.sum()
memory_weights = np.array([0.1, 0.3, 0.3, 0.2])
memory_weights = memory_weights / memory_weights.sum()

rng = np.random.default_rng()
df = pl.DataFrame(
    {
        "days": rng.choice(90, size=NUM_PILOTS, p=day_weights),
        "hours": rng.integers(0, 25, size=NUM_PILOTS),
        "minutes": rng.integers(0, 61, size=NUM_PILOTS),
        "seconds": rng.integers(0, 61, size=NUM_PILOTS),
        "status": rng.choice(
            ["Running", "Waiting", "Done", "Failed"], size=NUM_PILOTS, p=status_weights
        ),
        "cores": rng.choice([1, 8, 16, 256], size=NUM_PILOTS, p=core_weights),
        "memory": rng.choice(
            [1024, 2048, 4096, 8092], size=NUM_PILOTS, p=memory_weights
        ),
    }
)

df = df.with_columns(
    (
        pl.lit(start_date)
        + pl.duration(days="days", hours="hours", minutes="minutes", seconds="seconds")
    ).alias("update_time")
)

conn.execute(
    "INSERT INTO Pilots (UpdateTime, Status) SELECT update_time, status FROM df"
)
conn.execute(
    "INSERT INTO PilotAttributes (PilotID, Cores, MemoryMB) SELECT row_number() OVER (), cores, memory FROM df"
)
conn.execute("EXPORT DATABASE 'pilots' (FORMAT parquet);")
