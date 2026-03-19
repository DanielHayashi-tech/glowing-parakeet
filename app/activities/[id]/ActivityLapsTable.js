"use client";

import { useState } from "react";

export default function ActivityLapsTable({ laps }) {
  const [selectedLapId, setSelectedLapId] = useState(laps[0]?.lap_id ?? null);

  if (!laps.length) {
    return <div className="empty-state">No lap data found for this activity.</div>;
  }

  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Segment</th>
            <th>Lap</th>
            <th>Time</th>
            <th>Cumulative Time</th>
            <th>Distance</th>
            <th>Cumulative Dist</th>
            <th>Avg Pace</th>
            <th>Avg HR</th>
            <th>Max HR</th>
            <th>Cadence</th>
          </tr>
        </thead>
        <tbody>
          {laps.map((lap) => {
            const isSelected = lap.lap_id === selectedLapId;
            return (
              <tr
                className={isSelected ? "lap-row-selected" : ""}
                key={lap.lap_id}
                onClick={() => setSelectedLapId(lap.lap_id)}
              >
                <td>
                  <button
                    className={`lap-select-button${isSelected ? " active" : ""}`}
                    onClick={() => setSelectedLapId(lap.lap_id)}
                    type="button"
                  >
                    {lap.segment_label}
                  </button>
                </td>
                <td>{lap.lap_index}</td>
                <td>{lap.lap_duration_minutes} min</td>
                <td>{lap.cumulative_duration_minutes} min</td>
                <td>{lap.lap_distance_miles} mi</td>
                <td>{lap.cumulative_distance_miles} mi</td>
                <td>{lap.lap_pace_min_per_mile} min/mi</td>
                <td>{lap.lap_avg_heart_rate_bpm} bpm</td>
                <td>{lap.lap_max_heart_rate_bpm} bpm</td>
                <td>{lap.lap_avg_cadence_spm} spm</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
