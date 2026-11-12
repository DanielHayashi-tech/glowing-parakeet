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

function shortDateLabel(iso) {
  const [year, month, day] = iso.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day)).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC"
  });
}

function summarizeRunWindow(runs, startIso, endIso) {
  const inWindow = runs.filter(
    (run) => run.activity_date_local >= startIso && run.activity_date_local <= endIso
  );
  const miles = inWindow.reduce((sum, run) => sum + Number(run.distance_miles || 0), 0);
  const minutes = inWindow.reduce((sum, run) => sum + Number(run.duration_minutes || 0), 0);
  const heartRates = inWindow
    .map((run) => Number(run.avg_heart_rate_bpm))
    .filter((value) => Number.isFinite(value) && value > 0);

  return {
    runCount: inWindow.length,
    miles: Number(miles.toFixed(2)),
    minutes: Number(minutes.toFixed(1)),
    paceMinPerMile: miles > 0 ? minutes / miles : null,
    avgHeartRate: heartRates.length
      ? heartRates.reduce((sum, value) => sum + value, 0) / heartRates.length
      : null
  };
}

// Running-only view for the dashboard visuals. Anchored to the latest activity
// date (like the week calendar) so the page still reads well between syncs.
export function getTrainingDashboard() {
  const anchor = latestActivityDate();
  if (!anchor) {
    return null;
  }

  const runs = getOverviewActivities().filter(
    (activity) => activity.activity_type === "running"
  );

  const dayCount = 30;
  const days = [];
  for (let offset = dayCount - 1; offset >= 0; offset -= 1) {
    const date = new Date(anchor);
    date.setUTCDate(date.getUTCDate() - offset);
    const iso = isoDateFromDate(date);
    const dayRuns = runs.filter((run) => run.activity_date_local === iso);
    days.push({
      iso,
      label: shortDateLabel(iso),
      miles: Number(
        dayRuns.reduce((sum, run) => sum + Number(run.distance_miles || 0), 0).toFixed(2)
      ),
      minutes: Number(
        dayRuns.reduce((sum, run) => sum + Number(run.duration_minutes || 0), 0).toFixed(1)
      ),
      runCount: dayRuns.length
    });
  }

  const startIso = days[0].iso;
  const paceRuns = runs
    .filter(
      (run) =>
        run.activity_date_local >= startIso &&
        Number(run.distance_miles) > 0 &&
        Number(run.pace_min_per_mile) > 0
    )
    .map((run) => ({
      id: run.activity_id,
      iso: run.activity_date_local,
      dayIndex: days.findIndex((day) => day.iso === run.activity_date_local),
      label: shortDateLabel(run.activity_date_local),
      paceMinPerMile: Number(run.pace_min_per_mile),
      miles: Number(run.distance_miles),
      minutes: Number(run.duration_minutes),
      avgHeartRate: run.avg_heart_rate_bpm ? Number(run.avg_heart_rate_bpm) : null,
      treadmill: run.sub_sport === "treadmill"
    }))
    .sort((a, b) => a.iso.localeCompare(b.iso) || a.id - b.id);

  const isoOffset = (offset) => {
    const date = new Date(anchor);
    date.setUTCDate(date.getUTCDate() + offset);
    return isoDateFromDate(date);
  };

  return {
    anchorIso: isoDateFromDate(anchor),
    days,
    paceRuns,
    last7: summarizeRunWindow(runs, isoOffset(-6), isoOffset(0)),
    prev7: summarizeRunWindow(runs, isoOffset(-13), isoOffset(-7)),
    last30: summarizeRunWindow(runs, startIso, isoOffset(0))
  };
}

const SEMICIRCLE_TO_DEGREES = 180 / 2 ** 31;

// Samples without a GPS fix are stored as NULL by the importer.
const VALID_FIX_SQL = `
  s.latitude_semicircles IS NOT NULL AND s.longitude_semicircles IS NOT NULL
`;

// Latest run that has GPS (treadmill runs do not). Returns a downsampled track
// projected into a unit box plus pace / heart-rate profiles against distance.
export function getLatestRunRoute() {
  const run = queryOne(
    `
      SELECT a.id, a.started_at_utc, a.timezone, a.distance_m, a.duration_seconds,
             a.avg_heart_rate_bpm
      FROM activities a
      WHERE a.activity_type = 'running'
        AND EXISTS (
          SELECT 1 FROM activity_samples s
          WHERE s.activity_id = a.id AND ${VALID_FIX_SQL}
        )
      ORDER BY a.started_at_utc DESC
      LIMIT 1
    `
  );
  if (!run) {
    return null;
  }

  const rows = queryAll(
    `
      SELECT s.elapsed_seconds, s.distance_m, s.heart_rate_bpm,
             s.latitude_semicircles, s.longitude_semicircles
      FROM activity_samples s
      WHERE s.activity_id = ?
        AND ${VALID_FIX_SQL}
        AND s.distance_m IS NOT NULL
      ORDER BY s.elapsed_seconds
    `,
    [run.id]
  );
  if (rows.length < 20) {
    return null;
  }

  const targetPoints = 240;
  const stride = Math.max(1, Math.floor(rows.length / targetPoints));
  const sampled = rows.filter((_, index) => index % stride === 0 || index === rows.length - 1);

  const latitudes = sampled.map((row) => row.latitude_semicircles * SEMICIRCLE_TO_DEGREES);
  const longitudes = sampled.map((row) => row.longitude_semicircles * SEMICIRCLE_TO_DEGREES);
  const meanLatitude = latitudes.reduce((sum, value) => sum + value, 0) / latitudes.length;
  const lonScale = Math.cos((meanLatitude * Math.PI) / 180);

  const xs = longitudes.map((value) => value * lonScale);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...latitudes);
  const maxY = Math.max(...latitudes);
  const span = Math.max(maxX - minX, maxY - minY) || 1;

  const lookback = 6;
  const points = sampled.map((row, index) => {
    const previous = sampled[Math.max(0, index - lookback)];
    const deltaMiles = (row.distance_m - previous.distance_m) / 1609.344;
    const deltaMinutes = (row.elapsed_seconds - previous.elapsed_seconds) / 60;
    const pace = deltaMiles > 0.02 ? deltaMinutes / deltaMiles : null;
    return {
      // y is flipped so north is up on screen.
      x: (xs[index] - minX) / span,
      y: (maxY - latitudes[index]) / span,
      miles: Number((row.distance_m / 1609.344).toFixed(3)),
      paceMinPerMile: pace && pace >= 3 && pace <= 20 ? Number(pace.toFixed(2)) : null,
      heartRate: row.heart_rate_bpm ? Number(row.heart_rate_bpm) : null
    };
  });

  const localDate = isoDateInTimezone(run.started_at_utc, run.timezone);
  return {
    activityId: run.id,
    dateLabel: shortDateLabel(localDate),
    miles: Number((run.distance_m / 1609.344).toFixed(2)),
    minutes: Number((run.duration_seconds / 60).toFixed(1)),
    avgHeartRate: run.avg_heart_rate_bpm ? Number(run.avg_heart_rate_bpm) : null,
    aspect: (maxX - minX) / span,
    heightRatio: (maxY - minY) / span,
    points
  };
}

function average(values) {
  const usable = values.filter((value) => Number.isFinite(value));
  return usable.length ? usable.reduce((sum, value) => sum + value, 0) / usable.length : null;
}

// Last 30 days of wellness (sleep, resting HR, HRV, body battery), anchored to the
// newest day Garmin has given us. Returns null until the first wellness sync.
export function getRecoveryDashboard() {
  const newest = queryOne(`SELECT MAX(calendar_date) AS day FROM wellness_daily`)?.day;
  if (!newest) {
    return null;
  }

  const [year, month, day] = newest.split("-").map(Number);
  const anchor = new Date(Date.UTC(year, month - 1, day));
  const rows = queryAll(
    `
      SELECT *
      FROM wellness_daily
      WHERE calendar_date > date(?, '-30 day') AND calendar_date <= ?
    `,
    [newest, newest]
  );
  const byDate = new Map(rows.map((row) => [row.calendar_date, row]));

  const days = [];
  for (let offset = 29; offset >= 0; offset -= 1) {
    const date = new Date(anchor);
    date.setUTCDate(date.getUTCDate() - offset);
    const iso = isoDateFromDate(date);
    const row = byDate.get(iso);
    const hours = (seconds) => (seconds == null ? null : Number((seconds / 3600).toFixed(2)));
    days.push({
      iso,
      label: shortDateLabel(iso),
      sleepHours: hours(row?.sleep_seconds),
      sleepScore: row?.sleep_score ?? null,
      deepHours: hours(row?.deep_sleep_seconds),
      lightHours: hours(row?.light_sleep_seconds),
      remHours: hours(row?.rem_sleep_seconds),
      awakeHours: hours(row?.awake_seconds),
      restingHr: row?.resting_hr_bpm ?? null,
      hrv: row?.hrv_last_night_avg ?? null,
      hrvLow: row?.hrv_balanced_low ?? null,
      hrvHigh: row?.hrv_balanced_upper ?? null,
      hrvStatus: row?.hrv_status ?? null,
      bodyBatteryAtWake: row?.body_battery_at_wake ?? null
    });
  }

  const latest = [...days].reverse().find((entry) => entry.sleepHours !== null) ?? days.at(-1);
  const priorWeek = days.slice(-8, -1);
  return {
    newestIso: newest,
    days,
    latest,
    priorSleepHours: average(priorWeek.map((entry) => entry.sleepHours)),
    priorRestingHr: average(priorWeek.map((entry) => entry.restingHr)),
    priorHrv: average(priorWeek.map((entry) => entry.hrv)),
    priorBodyBattery: average(priorWeek.map((entry) => entry.bodyBatteryAtWake))
  };
}
