import duckdb
import random
from datetime import datetime, timedelta

# Create an in-memory DuckDB database
conn = duckdb.connect(database=":memory:")

# Create the sequence
conn.execute("""
CREATE SEQUENCE IF NOT EXISTS pilot_ids START 1;
""")

# Create the 'Pilots' table
conn.execute("""
CREATE TABLE Pilots (
    PilotID INTEGER PRIMARY KEY DEFAULT nextval('pilot_ids'),
    UpdateTime TIMESTAMP,
    Status ENUM('Running', 'Waiting', 'Done', 'Failed')
);
""")

# Create the 'PilotAttributes' table
conn.execute("""
CREATE TABLE PilotAttributes (
    PilotID INTEGER PRIMARY KEY,
    Cores USMALLINT,
    MemoryMB UINTEGER,
    FOREIGN KEY (PilotID) REFERENCES Pilots(PilotID)
);
""")

# Generate random data for the last days
start_date = datetime.now() - timedelta(days=2)
end_date = datetime.now()


# Insert random data into 'Pilots' and 'PilotAttributes'
def random_multiple_of_x(x=1, from_n=1, to_n=1000):
    # Calculate the number of steps between from_n and to_n
    steps = (to_n - from_n) // x + 1
    # Generate a random step and multiply by x
    return random.randint(1, steps) * x


statuses = ["Running", "Waiting", "Done", "Failed"]

for pilot_id in range(1, 1_000_001):
    update_time = start_date + timedelta(
        days=random.randint(0, 1),
        hours=random.randint(0, 24),
        minutes=random.randint(0, 60),
        seconds=random.randint(0, 60),
    )
    status = random.choice(statuses)
    conn.execute(
        "INSERT INTO Pilots (UpdateTime, Status) VALUES (?, ?)", (update_time, status)
    )

    cores = random_multiple_of_x(8, 1, 16)
    memory_mb = random_multiple_of_x(1024, 1024, 32768)
    conn.execute(
        "INSERT INTO PilotAttributes (PilotID, Cores, MemoryMB) VALUES (?, ?, ?)",
        (pilot_id, cores, memory_mb),
    )
conn.execute("EXPORT DATABASE 'pilots' (FORMAT parquet);")
