import duckdb
import pandas as pd
import matplotlib.pyplot as plt

result_df = duckdb.sql("""
SELECT 
time_bucket,
cores,
SUM(pilot_count) AS total_pilots
FROM (
SELECT
    time_bucket(INTERVAL '15 Minutes', UpdateTime) AS time_bucket,
    pilotattributes.cores AS cores,
    COUNT(pilots.PilotID) AS pilot_count
FROM 'pilots/pilots.parquet'
JOIN 'pilots/pilotattributes.parquet'
    ON pilots.PilotID = pilotattributes.PilotID
GROUP BY time_bucket, cores
) AS subquery
GROUP BY time_bucket, cores
ORDER BY time_bucket;
""").fetchdf()

pivot_df = result_df.pivot(
    index="time_bucket", columns="cores", values="total_pilots"
)

plt.figure(figsize=(14, 7))
for cores in pivot_df.columns:
    plt.plot(pivot_df.index, pivot_df[cores], label=f"Cores: {cores}")

plt.title("Number of Pilots Over Time (Grouped by Cores)")
plt.xlabel("Time Bucket")
plt.ylabel("Number of Pilots")
plt.legend(title="Cores")
plt.grid(True)
plt.xticks(rotation=45)
plt.tight_layout()
plt.show()
