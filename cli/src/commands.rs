// src/commands.rs
use clap::{Subcommand, ValueEnum};
use serde::Deserialize;

#[derive(Subcommand)]
pub enum Commands {
    /// List all categories
    ListCategories,

    /// Create a new category
    CreateCategory {
        /// Name of the category
        name: String,
        /// Color in hex, e.g. #CCCCCC
        #[arg(short, long, default_value = "#CCCCCC")]
        color: String,
    },

    /// List all tasks
    ListTasks,

    /// Create an event task
    CreateEvent {
        /// Title of the event
        title: String,
        /// Start time (ISO datetime)
        #[arg(long)]
        start: String,
        /// End time (ISO datetime)
        #[arg(long)]
        end: String,
        /// Description (optional)
        #[arg(long)]
        description: Option<String>,
    },

    /// Create a todo task
    CreateTodo {
        /// Title of the todo
        title: String,
        /// Estimate in minutes
        #[arg(long)]
        estimate: i32,
        /// Deadline (ISO datetime)
        #[arg(long)]
        deadline: String,
        /// Priority (default 0)
        #[arg(long, default_value_t = 0)]
        priority: i32,
        /// Description (optional)
        #[arg(long)]
        description: Option<String>,
    },

    /// Update a task
    UpdateTask {
        /// ID of the task to update
        task_id: i32,
        /// New status
        #[arg(long)]
        status: Option<String>,
        /// New title
        #[arg(long)]
        title: Option<String>,
        /// New priority
        #[arg(long)]
        priority: Option<i32>,
    },

    /// Delete a task
    DeleteTask {
        /// ID of the task to delete
        task_id: i32,
    },

    /// Sync calendar events into local DB
    SyncCalendar,

    /// Auto-schedule all unscheduled TODOs according to availability & weights
    AutoSchedule {
        /// Optional path to JSON config file with `availability` and `weights`.
        #[arg(long, value_name = "FILE")]
        config: Option<String>,
    },

    /// Push a single task/event to Google Calendar
    PushTask {
        /// Local task ID to push
        task_id: i32,
    },

    /// Push all events and scheduled todos to Google Calendar
    PushAll,
    /// Generate shell completion scripts
    Completions {
        /// The shell to generate the script for
        #[arg(value_enum)]
        shell: Shell,
    },
}

// Response types
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

