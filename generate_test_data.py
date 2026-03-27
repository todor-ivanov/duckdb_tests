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
start_date = datetime.now() - timedelta(days=90)
end_date = datetime.now()


def random_multiple_of_x(x=1, from_n=1, to_n=1000, weights=None):
    """helper to generate random data into 'Pilots' and 'PilotAttributes'"""
    # Calculate the number of steps between from_n and to_n
    steps = (to_n - from_n) // x + 1

    # Generate a list of all possible multiples
    multiples = [from_n + i * x for i in range(steps)]
    # Use random.choices if weights are provided, otherwise use random.choice
    if weights is not None:
        return random.choices(multiples, weights=weights, k=1)[0]
    else:
        return random.choices(multiples)


statuses = ["Running", "Waiting", "Done", "Failed"]
status_weights = [0.5, 0.1, 0.39, 0.01]
cores = [1, 8, 16, 256]
core_weights = [0.6, 0.1, 0.25, 0.05]
memory = [1024, 2048, 4096, 8092]
memory_weights = [0.1, 0.3, 0.3, 0.2]

NUM_PILOTS = 100_000

update_times = [
    start_date + timedelta(
        days=random.randint(0, 1),
        hours=random.randint(0, 24),
        minutes=random.randint(0, 60),
        seconds=random.randint(0, 60),
    )
    for _ in range(NUM_PILOTS)
]
status_list = random.choices(statuses, weights=status_weights, k=NUM_PILOTS)
cores_list = random.choices(cores, weights=core_weights, k=NUM_PILOTS)
memory_list = random.choices(memory, weights=memory_weights, k=NUM_PILOTS)

conn.executemany(
    "INSERT INTO Pilots (UpdateTime, Status) VALUES (?, ?)",
    zip(update_times, status_list)
)
conn.executemany(
    "INSERT INTO PilotAttributes (PilotID, Cores, MemoryMB) VALUES (?, ?, ?)",
    zip(range(1, NUM_PILOTS + 1), cores_list, memory_list)
)
conn.execute("EXPORT DATABASE 'pilots' (FORMAT parquet);")
