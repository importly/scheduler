use chrono::{Datelike, Duration, Local, NaiveDate, NaiveTime, Weekday};
use regex::Regex;
use std::error::Error;

/// Leap year check
fn is_leap_year(year: i32) -> bool {
    (year % 4 == 0 && year % 100 != 0) || (year % 400 == 0)
}

/// Days in month
fn days_in_month(year: i32, month: u32) -> u32 {
    match month {
        1 | 3 | 5 | 7 | 8 | 10 | 12 => 31,
        4 | 6 | 9 | 11 => 30,
        2 => if is_leap_year(year) { 29 } else { 28 },
        _ => 0,
    }
}

/// Add/subtract months, clamp day
fn add_months(date: NaiveDate, months_to_add: i32) -> NaiveDate {
    let mut year = date.year();
    let mut month_calc = date.month() as i32 + months_to_add;
    let mut day = date.day();

    year += (month_calc - 1) / 12;
    month_calc = (month_calc - 1) % 12 + 1;

    if month_calc <= 0 {
        month_calc += 12;
        year -= 1;
    }

    let new_month = month_calc as u32;
    day = day.min(days_in_month(year, new_month));
    NaiveDate::from_ymd_opt(year, new_month, day).unwrap()
}

/// Last day of a month
fn last_day_of_month(year: i32, month: u32) -> NaiveDate {
    let day = days_in_month(year, month);
    NaiveDate::from_ymd_opt(year, month, day).unwrap()
}

/// Parse natural date/time to "YYYY-MM-DDTHH:MM:SS"
pub fn parse_deadline(input: &str) -> Result<String, Box<dyn Error>> {
    let raw = input.trim();
    let s = raw.strip_prefix("due ").unwrap_or(raw).trim().to_lowercase();

    let (date_part, time_part_str) = if let Some(idx) = s.rfind(" at ") {
        let (d, t) = s.split_at(idx);
        (d.trim(), Some(t[4..].trim()))
    } else {
        (s.as_str(), None)
    };

    let default_time = NaiveTime::from_hms_opt(21, 0, 0).unwrap();

    /// Parse "5 pm", "5:00 pm", etc.
    fn parse_time(t: &str) -> Option<NaiveTime> {
        let t_up = t.trim().to_ascii_uppercase();
        let fmts = ["%I:%M %p", "%I %p"];

        for fmt in &fmts {
            if let Ok(tm) = NaiveTime::parse_from_str(&t_up, fmt) {
                return Some(tm);
            }
        }

        let re = Regex::new(r"^(?P<h>\d{1,2})\s*(?P<ap>(?:AM|PM))$").unwrap();
        if let Some(cap) = re.captures(&t_up) {
            if let Ok(hour12) = cap["h"].parse::<u32>() {
                if hour12 >= 1 && hour12 <= 12 {
                    let mut hour24 = hour12;
                    if &cap["ap"] == "PM" && hour12 != 12 {
                        hour24 += 12;
                    }
                    if &cap["ap"] == "AM" && hour12 == 12 {
                        hour24 = 0;
                    }
                    return NaiveTime::from_hms_opt(hour24, 0, 0);
                }
            }
        }
        None
    }

    let time = if let Some(tstr) = time_part_str {
        parse_time(tstr)
            .ok_or_else(|| format!("Invalid time format: '{}'", tstr))?
    } else {
        default_time
    };

    let today = Local::now().date_naive();

    let date = match date_part {
        "today" => today,
        "tmr" | "tomorrow" => today + Duration::days(1),
        "day after tomorrow" | "day after tmr" => today + Duration::days(2),
        "yesterday" => today - Duration::days(1),
        "day before yesterday" => today - Duration::days(2),
        "next week" => today + Duration::weeks(1),
        "week after next week" => today + Duration::weeks(2),
        "end of this week" | "end of week" => {
            let today_wd = today.weekday().number_from_monday();
            let friday_wd = Weekday::Fri.number_from_monday();
            let delta = friday_wd as i8 - today_wd as i8;
            today + Duration::days(delta as i64)
        }
        "next month" => add_months(today, 1),
        "end of this month" | "end of month" => last_day_of_month(today.year(), today.month()),
        "end of next month" => {
            let nm = add_months(today, 1);
            last_day_of_month(nm.year(), nm.month())
        }
        other => {
            let re = Regex::new(r"^(\d{1,2})/(\d{1,2})/(\d{2})$").map_err(|e| e.to_string())?;
            if let Some(cap) = re.captures(other) {
                let m: u32 = cap[1].parse()?;
                let d: u32 = cap[2].parse()?;
                let y: u32 = 2000 + cap[3].parse::<u32>()?;
                NaiveDate::from_ymd_opt(y as i32, m, d)
                    .ok_or_else(|| "Invalid calendar date".to_string())?
            } else {
                return Err(format!("Unrecognized date: '{}'", other).into());
            }
        }
    };

    Ok(format!("{}T{}", date.format("%Y-%m-%d"), time.format("%H:%M:%S")))
}
