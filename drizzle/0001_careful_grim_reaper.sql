CREATE TABLE `job_events` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`job_id` text NOT NULL,
	`level` text NOT NULL,
	`event_type` text NOT NULL,
	`message` text NOT NULL,
	`details_json` text DEFAULT '{}' NOT NULL,
	`created_at` text NOT NULL,
	FOREIGN KEY (`job_id`) REFERENCES `jobs`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE INDEX `idx_job_events_job_id_id` ON `job_events` (`job_id`,`id`);--> statement-breakpoint
CREATE TABLE `job_items` (
	`id` text PRIMARY KEY NOT NULL,
	`job_id` text NOT NULL,
	`input_hash` text NOT NULL,
	`input_ref` text NOT NULL,
	`position` integer NOT NULL,
	`state` text DEFAULT 'pending' NOT NULL,
	`attempt_count` integer DEFAULT 0 NOT NULL,
	`cache_key` text,
	`output_json` text,
	`error_json` text,
	`updated_at` text NOT NULL,
	FOREIGN KEY (`job_id`) REFERENCES `jobs`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE UNIQUE INDEX `idx_job_items_job_position` ON `job_items` (`job_id`,`position`);--> statement-breakpoint
CREATE INDEX `idx_job_items_job_state_position` ON `job_items` (`job_id`,`state`,`position`);--> statement-breakpoint
CREATE TABLE `processing_cache` (
	`cache_key` text PRIMARY KEY NOT NULL,
	`processor_id` text NOT NULL,
	`processor_version` text NOT NULL,
	`input_hash` text NOT NULL,
	`parameters_hash` text NOT NULL,
	`model_revision` text,
	`output_json` text NOT NULL,
	`created_at` text NOT NULL,
	`last_accessed_at` text NOT NULL,
	`hit_count` integer DEFAULT 0 NOT NULL
);
--> statement-breakpoint
CREATE INDEX `idx_processing_cache_processor_input` ON `processing_cache` (`processor_id`,`processor_version`,`input_hash`);--> statement-breakpoint
DROP INDEX `idx_dataset_versions_project`;--> statement-breakpoint
CREATE UNIQUE INDEX `idx_dataset_versions_project` ON `dataset_versions` (`project_id`,`version`);--> statement-breakpoint
ALTER TABLE `jobs` ADD `profile` text DEFAULT 'balanced' NOT NULL;--> statement-breakpoint
ALTER TABLE `jobs` ADD `processor_id` text DEFAULT 'core.identity' NOT NULL;--> statement-breakpoint
ALTER TABLE `jobs` ADD `processor_version` text DEFAULT '1.0.0' NOT NULL;--> statement-breakpoint
ALTER TABLE `jobs` ADD `deterministic` integer DEFAULT true NOT NULL;--> statement-breakpoint
ALTER TABLE `jobs` ADD `cacheable` integer DEFAULT true NOT NULL;--> statement-breakpoint
ALTER TABLE `jobs` ADD `model_revision` text;--> statement-breakpoint
ALTER TABLE `jobs` ADD `parameters_json` text DEFAULT '{}' NOT NULL;--> statement-breakpoint
ALTER TABLE `jobs` ADD `resource_hints_json` text DEFAULT '{}' NOT NULL;--> statement-breakpoint
ALTER TABLE `jobs` ADD `total_items` integer DEFAULT 0 NOT NULL;--> statement-breakpoint
ALTER TABLE `jobs` ADD `processed_count` integer DEFAULT 0 NOT NULL;--> statement-breakpoint
ALTER TABLE `jobs` ADD `failed_count` integer DEFAULT 0 NOT NULL;--> statement-breakpoint
ALTER TABLE `jobs` ADD `skipped_count` integer DEFAULT 0 NOT NULL;--> statement-breakpoint
ALTER TABLE `jobs` ADD `cached_count` integer DEFAULT 0 NOT NULL;--> statement-breakpoint
ALTER TABLE `jobs` ADD `lease_owner` text;--> statement-breakpoint
ALTER TABLE `jobs` ADD `lease_expires_at` text;--> statement-breakpoint
ALTER TABLE `jobs` ADD `last_error` text;--> statement-breakpoint
ALTER TABLE `jobs` ADD `started_at` text;--> statement-breakpoint
ALTER TABLE `jobs` ADD `completed_at` text;--> statement-breakpoint
CREATE INDEX `idx_jobs_claimable` ON `jobs` (`state`,`created_at`);