use clap::{Subcommand, ValueEnum};
use serde::Deserialize;

#[derive(Subcommand)]
pub enum Commands {
    #[command(alias = "lc")]
    ListCategories,

    #[command(alias = "cc")]
    CreateCategory {
        name: String,
        #[arg(short, long, default_value = "#CCCCCC")]
        color: String,
    },

    #[command(alias = "lt")]
    ListTasks,

    #[command(alias = "ce")]
    CreateEvent {
        title: String,
        #[arg(short = 's', long)]
        start: String,
        #[arg(short = 'e', long)]
        end: String,
        #[arg(short = 'd', long)]
        description: Option<String>,
    },

    #[command(alias = "ct")]
    CreateTodo {
        title: String,
        #[arg(short = 'e', long)]
        estimate: i32,
        #[arg(short = 'd', long)]
        deadline: String,
        #[arg(short = 'p', long, default_value_t = 0)]
        priority: i32,
        #[arg(short = 'D', long)]
        description: Option<String>,
    },

    #[command(alias = "ut")]
    UpdateTask {
        task_id: i32,
        #[arg(short = 's', long)]
        status: Option<String>,
        #[arg(short = 't', long)]
        title: Option<String>,
        #[arg(short = 'p', long)]
        priority: Option<i32>,
    },

    #[command(alias = "dt")]
    DeleteTask {
        task_id: i32,
    },

    #[command(alias = "sc")]
    SyncCalendar,

    #[command(alias = "as")]
    AutoSchedule {
        #[arg(short = 'c', long, value_name = "FILE")]
        config: Option<String>,
    },

    #[command(alias = "pt")]
    PushTask {
        task_id: i32,
    },

    #[command(alias = "pa")]
    PushAll,

    #[command(alias = "comp")]
    Completions {
        #[arg(value_enum)]
        shell: Shell,
    },
}

#[derive(Deserialize)]
pub struct Category {
    pub id: i32,
    pub name: String,
    pub color: String,
}

#[derive(Deserialize)]
pub struct Task {
    pub id: i32,
    pub title: String,
    #[serde(rename = "type")]
    pub kind: String,
    pub status: Option<String>,
    pub priority: Option<i32>,
    pub estimate: Option<i32>,
    pub duration: Option<i32>,
    pub deadline: Option<String>,
    pub start_time: Option<String>,
    pub scheduled_for: Option<String>,
    pub category: Option<Category>,
}

#[derive(Deserialize)]
pub struct SyncResult {
    pub imported: Option<i32>,
}

#[derive(Deserialize)]
pub struct AutoScheduleResult {
    pub status: Option<String>,
}

#[derive(Deserialize)]
pub struct PushTaskResult {
    pub google_event_id: Option<String>,
}

#[derive(Deserialize)]
pub struct PushAllResult {
    pub pushed: Option<u32>,
    pub updated: Option<u32>,
}

#[derive(ValueEnum, Clone)]
pub enum Shell {
    Bash,
    Zsh,
    Fish,
    PowerShell,
    Elvish,
}
