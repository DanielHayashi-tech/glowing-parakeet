import { queryAll, queryOne } from "@/lib/db";
import {
  formatIsoDateToDisplay,
  formatWeekRange,
  isoDateInTimezone
} from "@/lib/format";

export function getDashboardSummary() {
  return queryOne(
    `
      SELECT
        COUNT(*) AS activity_count,
        ROUND(SUM(distance_m) / 1609.344, 2) AS total_miles,
        ROUND(SUM(duration_seconds) / 3600.0, 2) AS total_hours,
        ROUND(AVG(avg_heart_rate_bpm), 1) AS avg_heart_rate_bpm
      FROM activities
    `
  );
}

export function getActivities() {
  return getOverviewActivities();
}

export function getWeeklySummary() {
  return queryAll(
    `
      SELECT *
      FROM vw_weekly_activity_summary
      ORDER BY activity_week_utc DESC
    `
  );
}

export function getActivityById(activityId) {
  const activity = queryOne(
    `
      SELECT *
      FROM vw_activity_overview
      WHERE activity_id = ?
    `,
    [activityId]
  );
  if (!activity) {
    return null;
  }
  return {
    ...activity,
    activity_date_local: isoDateInTimezone(
      activity.started_at_utc,
      activity.activity_timezone
    ),
    activity_date_display: formatIsoDateToDisplay(
      isoDateInTimezone(activity.started_at_utc, activity.activity_timezone)
    )
  };
}

export function getLapsForActivity(activityId) {
  let cumulativeMinutes = 0;
  let cumulativeMiles = 0;

  return queryAll(
    `
      SELECT *
      FROM vw_lap_overview
      WHERE activity_id = ?
      ORDER BY lap_index
    `,
    [activityId]
  ).map((lap) => {
    cumulativeMinutes += Number(lap.lap_duration_minutes || 0);
    cumulativeMiles += Number(lap.lap_distance_miles || 0);
    return {
      ...lap,
      segment_label: lap.lap_type || "Lap",
      cumulative_duration_minutes: Number(cumulativeMinutes.toFixed(2)),
      cumulative_distance_miles: Number(cumulativeMiles.toFixed(2))
    };
  });
}

export function getLatestActivity() {
  const activity = queryOne(
    `
      SELECT *
      FROM vw_activity_overview
      ORDER BY started_at_utc DESC
      LIMIT 1
    `
  );
  if (!activity) {
    return null;
  }
  return {
    ...activity,
    activity_date_local: isoDateInTimezone(
      activity.started_at_utc,
      activity.activity_timezone
    ),
    activity_date_display: formatIsoDateToDisplay(
      isoDateInTimezone(activity.started_at_utc, activity.activity_timezone)
    )
  };
}

function mondayStartForDate(date) {
  const normalized = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()));
  const day = normalized.getUTCDay();
  const diff = day === 0 ? -6 : 1 - day;
  normalized.setUTCDate(normalized.getUTCDate() + diff);
  return normalized;
}

function isoDateFromDate(date) {
  const yyyy = date.getUTCFullYear();
  const mm = String(date.getUTCMonth() + 1).padStart(2, "0");
  const dd = String(date.getUTCDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

function latestActivityDate() {
  const activities = queryAll(
    `
      SELECT started_at_utc, timezone
      FROM activities
    `
  );
  const localDates = activities
    .map((activity) => isoDateInTimezone(activity.started_at_utc, activity.timezone))
    .filter(Boolean)
    .sort();
  const latestDate = localDates.at(-1);
  if (!latestDate) {
    return null;
  }
  const [year, month, day] = latestDate.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day));
}

function getOverviewActivities() {
  return queryAll(
    `
      SELECT *
      FROM vw_activity_overview
      ORDER BY started_at_utc DESC
    `
  ).map((activity) => {
    const activityDateLocal = isoDateInTimezone(
      activity.started_at_utc,
      activity.activity_timezone
    );
    return {
      ...activity,
      activity_date_local: activityDateLocal,
      activity_date_display: formatIsoDateToDisplay(activityDateLocal)
    };
  });
}

export function getRecentActivityGroups() {
  const anchor = latestActivityDate();
  if (!anchor) {
    return [];
  }

  const start = new Date(anchor);
  start.setUTCDate(start.getUTCDate() - 6);
  const startIso = isoDateFromDate(start);

  const activities = getOverviewActivities().filter(
    (activity) => activity.activity_date_local >= startIso
  );

  const groups = new Map();
  for (const activity of activities) {
    const key = activity.activity_date_local;
    if (!groups.has(key)) {
      groups.set(key, {
        activityDate: key,
        activityDateDisplay: formatIsoDateToDisplay(key),
        items: []
      });
    }
    groups.get(key).items.push({
      ...activity
    });
  }

  return Array.from(groups.values());
}

export function getCurrentWeekCalendar() {
  const anchor = latestActivityDate();
  if (!anchor) {
    return [];
  }

  const weekStart = mondayStartForDate(anchor);
  const overviewActivities = getOverviewActivities();
  const days = [];

  for (let i = 0; i < 7; i += 1) {
    const current = new Date(weekStart);
    current.setUTCDate(weekStart.getUTCDate() + i);
    const iso = isoDateFromDate(current);

    const items = overviewActivities
      .filter((activity) => activity.activity_date_local === iso)
      .sort((a, b) => a.started_at_utc.localeCompare(b.started_at_utc));

    const totalMiles = items.reduce(
      (sum, item) => sum + Number(item.distance_miles || 0),
      0
    );
    const totalMinutes = items.reduce(
      (sum, item) => sum + Number(item.duration_minutes || 0),
      0
    );

    days.push({
      isoDate: iso,
      displayDate: formatIsoDateToDisplay(iso),
      dayLabel: current.toLocaleDateString("en-US", {
        weekday: "long",
        timeZone: "UTC"
      }),
      shortLabel: current.toLocaleDateString("en-US", {
        weekday: "short",
        timeZone: "UTC"
      }),
      activityCount: items.length,
      totalMiles: Number(totalMiles.toFixed(2)),
      totalMinutes: Number(totalMinutes.toFixed(1)),
      items
    });
  }

  return days;
}

function summarizeActivityBucket(items) {
  const count = items.length;
  const totalMiles = items.reduce(
    (sum, item) => sum + Number(item.distance_miles || 0),
    0
  );
  const totalMinutes = items.reduce(
    (sum, item) => sum + Number(item.duration_minutes || 0),
    0
  );

  return {
    count,
    totalMiles: Number(totalMiles.toFixed(2)),
    totalMinutes: Number(totalMinutes.toFixed(1))
  };
}

export function getWeeklySummaryLastTwelveWeeks() {
  const anchor = latestActivityDate();
  if (!anchor) {
    return { weeks: [], activityTypes: [] };
  }

  const currentMonday = mondayStartForDate(anchor);
  const firstMonday = new Date(currentMonday);
  firstMonday.setUTCDate(firstMonday.getUTCDate() - 77);
  const startIso = isoDateFromDate(firstMonday);

  const activities = getOverviewActivities().filter(
    (activity) => activity.activity_date_local >= startIso
  );

  const activityTypes = Array.from(
    new Set(activities.map((activity) => activity.activity_type).filter(Boolean))
  ).sort();

  const weeks = [];
  for (let i = 0; i < 12; i += 1) {
    const weekStart = new Date(firstMonday);
    weekStart.setUTCDate(firstMonday.getUTCDate() + i * 7);
    const weekStartIso = isoDateFromDate(weekStart);
    const weekEnd = new Date(weekStart);
    weekEnd.setUTCDate(weekEnd.getUTCDate() + 6);
    const weekEndIso = isoDateFromDate(weekEnd);

    const weekActivities = activities.filter(
      (activity) =>
        activity.activity_date_local >= weekStartIso &&
        activity.activity_date_local <= weekEndIso
    );

    const byType = {};
    for (const type of activityTypes) {
      const matching = weekActivities.filter(
        (activity) => activity.activity_type === type
      );
      byType[type] = summarizeActivityBucket(matching);
    }

    weeks.push({
      weekStartIso,
      weekEndIso,
      totalActivities: weekActivities.length,
      byType
    });
  }

  return { weeks, activityTypes };
}

export function getRunningMileageLastTwelveWeeks() {
  const weekly = getWeeklySummaryLastTwelveWeeks();
  const weeks = weekly.weeks.map((week) => {
    const running = week.byType.running ?? { count: 0, totalMiles: 0, totalMinutes: 0 };
    return {
      ...week,
      runCount: running.count,
      runningMiles: Number(running.totalMiles.toFixed(2)),
      runningMinutes: Number(running.totalMinutes.toFixed(1)),
      weekRangeLabel: formatWeekRange(week.weekStartIso)
    };
  });

  return {
    weeks,
    maxMiles: weeks.reduce(
      (max, week) => Math.max(max, Number(week.runningMiles || 0)),
      0
    )
  };
}
