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

# Sort by time_bucket and cores for correct cumulative sum
result_df = result_df.sort_values(by=["time_bucket", "cores"])

# Calculate cumulative sum per time_bucket
result_df["cumulative_pilots"] = result_df.groupby("time_bucket")[
    "total_pilots"
].cumsum()

# Pivot for plotting
pivot_df = result_df.pivot(
    index="time_bucket", columns="cores", values="cumulative_pilots"
)

# Plot the cumulative time series
plt.figure(figsize=(14, 7))
for cores in pivot_df.columns:
    plt.plot(pivot_df.index, pivot_df[cores], label=f"Cores: {cores}")

plt.title("Cumulative Number of Pilots Over Time (Grouped by Cores)")
plt.xlabel("Time Bucket")
plt.ylabel("Cumulative Number of Pilots")
plt.legend(title="Cores")
plt.grid(True)
plt.xticks(rotation=45)
plt.tight_layout()
plt.show()
