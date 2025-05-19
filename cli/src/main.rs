// src/main.rs
mod commands;
mod date_parser;

use clap::{CommandFactory, Parser};
use commands::{Category, Commands, SyncResult, Task, AutoScheduleResult, PushTaskResult, PushAllResult, Shell as CliShell};
use reqwest;
use serde_json::{json, Value};
use std::fs;
use clap_complete::generate;
use crate::date_parser::parse_deadline;

const API_URL: &str = "http://127.0.0.1:8000";

#[derive(Parser)]
#[command(name = "todo", about = "CLI for scheduler")]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let cli = Cli::parse();

    // handle completions:
    if let Commands::Completions { shell } = &cli.command {
        // Convert our CmdShell enum into clap_complete::Shell
        let mut app = Cli::command();
        let generator = match shell {
            CliShell::Bash        => clap_complete::Shell::Bash,
            CliShell::Zsh         => clap_complete::Shell::Zsh,
            CliShell::Fish        => clap_complete::Shell::Fish,
            CliShell::PowerShell  => clap_complete::Shell::PowerShell,
            CliShell::Elvish      => clap_complete::Shell::Elvish,
        };
        generate(generator, &mut app, "todo", &mut std::io::stdout());
        return Ok(());
    }
    
    let client = reqwest::Client::new();
    match cli.command {
        Commands::ListCategories => {
            let resp = client.get(format!("{}/categories/", API_URL)).send().await?;
            resp.error_for_status_ref()?;
            let cats: Vec<Category> = resp.json().await?;
            for c in cats {
                println!("[{}] {} (color={})", c.id, c.name, c.color);
            }
        }

        Commands::CreateCategory { name, color } => {
            let payload = json!({ "name": name, "color": color });
            let resp = client.post(format!("{}/categories/", API_URL))
                .json(&payload)
                .send()
                .await?;
            resp.error_for_status_ref()?;
            let c: Category = resp.json().await?;
            println!("Created category [ID {}] {}", c.id, c.name);
        }

        Commands::ListTasks => {
            let resp = client.get(format!("{}/tasks/", API_URL)).send().await?;
            resp.error_for_status_ref()?;
            let tasks: Vec<Task> = resp.json().await?;
            for t in tasks {
                println!(
                    "[{}] {} (type={}, status={}, priority={})",
                    t.id,
                    t.title,
                    t.kind,
                    t.status.unwrap_or_default(),
                    t.priority.unwrap_or(0)
                );
            }
        }

        Commands::CreateEvent { title, start, end, description } => {
            let mut payload = serde_json::Map::new();
            payload.insert("title".into(), Value::String(title));
            payload.insert("type".into(), Value::String("event".into()));
            payload.insert("start_time".into(), Value::String(start));
            payload.insert("end_time".into(), Value::String(end));
            if let Some(desc) = description {
                payload.insert("description".into(), Value::String(desc));
            }
            let resp = client.post(format!("{}/tasks/", API_URL))
                .json(&payload)
                .send()
                .await?;
            resp.error_for_status_ref()?;
            let t: Task = resp.json().await?;
            println!("Created event task [ID {}] {}", t.id, t.title);
        }

        Commands::CreateTodo { title, estimate, deadline, priority, description } => {

            let iso_deadline = parse_deadline(&deadline).map_err(|e| format!("Error parsing deadline `{}`: {}", deadline, e))?;
            let mut payload = serde_json::Map::new();
            
            println!("Parsed deadline: {}", iso_deadline);
            
            payload.insert("title".into(), Value::String(title));
            payload.insert("type".into(), Value::String("todo".into()));
            payload.insert("estimate".into(), Value::Number(estimate.into()));
            payload.insert("deadline".into(), Value::String(iso_deadline));
            payload.insert("priority".into(), Value::Number(priority.into()));
            if let Some(desc) = description {
                payload.insert("description".into(), Value::String(desc));
            }
            let resp = client.post(format!("{}/tasks/", API_URL))
                .json(&payload)
                .send()
                .await?;
            resp.error_for_status_ref()?;
            let t: Task = resp.json().await?;
            println!("Created todo task [ID {}] {}", t.id, t.title);
        }

        Commands::UpdateTask { task_id, status, title, priority } => {
            let mut payload = serde_json::Map::new();
            if let Some(s) = status {
                payload.insert("status".into(), Value::String(s));
            }
            if let Some(tl) = title {
                payload.insert("title".into(), Value::String(tl));
            }
            if let Some(p) = priority {
                payload.insert("priority".into(), Value::Number(p.into()));
            }
            if payload.is_empty() {
                eprintln!("No updates provided.");
                std::process::exit(1);
            }
            let resp = client.patch(format!("{}/tasks/{}", API_URL, task_id))
                .json(&payload)
                .send()
                .await?;
            resp.error_for_status_ref()?;
            let t: Task = resp.json().await?;
            println!(
                "Updated task [ID {}] status={} priority={}",
                t.id,
                t.status.unwrap_or_default(),
                t.priority.unwrap_or(0)
            );
        }

        Commands::DeleteTask { task_id } => {
            let resp = client.delete(format!("{}/tasks/{}", API_URL, task_id))
                .send()
                .await?;
            if resp.status() == reqwest::StatusCode::NO_CONTENT {
                println!("Deleted task ID {}", task_id);
            } else {
                resp.error_for_status_ref()?;
            }
        }

        Commands::SyncCalendar => {
            let resp = client.post(format!("{}/calendar/sync", API_URL))
                .send()
                .await?;
            resp.error_for_status_ref()?;
            let result: SyncResult = resp.json().await?;
            println!(
                "Imported {} events from Google Calendar.",
                result.imported.unwrap_or(0)
            );
        }

        Commands::AutoSchedule { config } => {
            // Use provided config file or default JSON
            let payload = if let Some(path) = config {
                let content = fs::read_to_string(&path)?;
                serde_json::from_str(&content)?
            } else {
                // default availability & weights for full week
                json!({
                    "availability": {
                        "0": [{ "start": "09:00", "end": "17:00" }],
                        "1": [{ "start": "09:00", "end": "17:00" }],
                        "2": [{ "start": "09:00", "end": "17:00" }],
                        "3": [{ "start": "09:00", "end": "17:00" }],
                        "4": [{ "start": "09:00", "end": "17:00" }],
                        "5": [{ "start": "10:00", "end": "14:00" }],
                        "6": []
                    },
                    "weights": { "priority": 1.0, "deadline": 100.0 }
                })
            };
            let resp = client.post(format!("{}/auto-schedule/", API_URL))
                .json(&payload)
                .send()
                .await?;
            resp.error_for_status_ref()?;
            let result: AutoScheduleResult = resp.json().await?;
            println!("Auto-schedule status: {}", result.status.unwrap_or_default());
        }

        Commands::PushTask { task_id } => {
            let resp = client.post(format!("{}/calendar/push/{}", API_URL, task_id))
                .send()
                .await?;
            resp.error_for_status_ref()?;
            let result: PushTaskResult = resp.json().await?;
            println!(
                "Pushed task [ID {}] to Google Calendar as {}",
                task_id,
                result.google_event_id.unwrap_or_default()
            );
        }

        Commands::PushAll => {
            let resp = client.post(format!("{}/calendar/push-all", API_URL))
                .send()
                .await?;
            resp.error_for_status_ref()?;
            let result: PushAllResult = resp.json().await?;
            println!(
                "Pushed {} new and updated {} existing events.",
                result.pushed.unwrap_or(0),
                result.updated.unwrap_or(0)
            );
        }
        _ => unreachable!(), // we've already returned on Completions
    }

    Ok(())
}
