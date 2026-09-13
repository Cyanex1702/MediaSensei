CREATE TABLE `acquisition_candidates` (
	`id` text PRIMARY KEY NOT NULL,
	`run_id` text NOT NULL,
	`query_id` text,
	`provider_id` text NOT NULL,
	`remote_id` text NOT NULL,
	`source_url` text NOT NULL,
	`canonical_url` text NOT NULL,
	`landing_page_url` text,
	`preview_url` text,
	`title` text,
	`description` text,
	`mime_type` text,
	`declared_width` integer,
	`declared_height` integer,
	`author` text,
	`license` text,
	`estimated_size` integer,
	`state` text NOT NULL,
	`download_attempts` integer DEFAULT 0 NOT NULL,
	`downloaded_bytes` integer DEFAULT 0 NOT NULL,
	`content_sha256` text,
	`asset_id` text,
	`metadata_json` text DEFAULT '{}' NOT NULL,
	`error` text,
	`created_at` text NOT NULL,
	`updated_at` text NOT NULL,
	FOREIGN KEY (`run_id`) REFERENCES `acquisition_runs`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`query_id`) REFERENCES `acquisition_queries`(`id`) ON UPDATE no action ON DELETE set null,
	FOREIGN KEY (`asset_id`) REFERENCES `assets`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE UNIQUE INDEX `idx_acquisition_candidates_run_provider_remote` ON `acquisition_candidates` (`run_id`,`provider_id`,`remote_id`);--> statement-breakpoint
CREATE UNIQUE INDEX `idx_acquisition_candidates_run_url` ON `acquisition_candidates` (`run_id`,`canonical_url`);--> statement-breakpoint
CREATE INDEX `idx_acquisition_candidates_run_state_created` ON `acquisition_candidates` (`run_id`,`state`,`created_at`,`id`);--> statement-breakpoint
CREATE TABLE `acquisition_decisions` (
	`id` text PRIMARY KEY NOT NULL,
	`run_id` text NOT NULL,
	`candidate_id` text NOT NULL,
	`decision` text NOT NULL,
	`reason` text NOT NULL,
	`evaluator_id` text NOT NULL,
	`evaluator_version` text NOT NULL,
	`scores_json` text DEFAULT '{}' NOT NULL,
	`human` integer DEFAULT 0 NOT NULL,
	`created_at` text NOT NULL,
	FOREIGN KEY (`run_id`) REFERENCES `acquisition_runs`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`candidate_id`) REFERENCES `acquisition_candidates`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE INDEX `idx_acquisition_decisions_run_reason` ON `acquisition_decisions` (`run_id`,`reason`,`created_at`);--> statement-breakpoint
CREATE TABLE `acquisition_plans` (
	`id` text PRIMARY KEY NOT NULL,
	`request_id` text NOT NULL,
	`project_id` text NOT NULL,
	`spec_json` text NOT NULL,
	`queries_json` text NOT NULL,
	`providers_json` text NOT NULL,
	`strategy_json` text NOT NULL,
	`estimated_min_candidates` integer NOT NULL,
	`estimated_max_candidates` integer NOT NULL,
	`state` text NOT NULL,
	`created_at` text NOT NULL,
	`updated_at` text NOT NULL,
	FOREIGN KEY (`request_id`) REFERENCES `acquisition_requests`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`project_id`) REFERENCES `projects`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE INDEX `idx_acquisition_plans_project_created` ON `acquisition_plans` (`project_id`,`created_at`,`id`);--> statement-breakpoint
CREATE TABLE `acquisition_queries` (
	`id` text PRIMARY KEY NOT NULL,
	`run_id` text NOT NULL,
	`provider_id` text NOT NULL,
	`query` text NOT NULL,
	`origin` text NOT NULL,
	`priority` real DEFAULT 1 NOT NULL,
	`cursor` text,
	`result_count` integer DEFAULT 0 NOT NULL,
	`evaluated_count` integer DEFAULT 0 NOT NULL,
	`accepted_count` integer DEFAULT 0 NOT NULL,
	`error_count` integer DEFAULT 0 NOT NULL,
	`exhausted` integer DEFAULT 0 NOT NULL,
	`created_at` text NOT NULL,
	`updated_at` text NOT NULL,
	FOREIGN KEY (`run_id`) REFERENCES `acquisition_runs`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE UNIQUE INDEX `idx_acquisition_queries_run_provider_query` ON `acquisition_queries` (`run_id`,`provider_id`,`query`);--> statement-breakpoint
CREATE INDEX `idx_acquisition_queries_run_priority` ON `acquisition_queries` (`run_id`,`exhausted`,`priority`,`created_at`);--> statement-breakpoint
CREATE TABLE `acquisition_requests` (
	`id` text PRIMARY KEY NOT NULL,
	`project_id` text NOT NULL,
	`original_prompt` text,
	`spec_json` text NOT NULL,
	`planner_id` text NOT NULL,
	`status` text NOT NULL,
	`created_at` text NOT NULL,
	`updated_at` text NOT NULL,
	FOREIGN KEY (`project_id`) REFERENCES `projects`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE INDEX `idx_acquisition_requests_project_created` ON `acquisition_requests` (`project_id`,`created_at`,`id`);--> statement-breakpoint
CREATE TABLE `acquisition_runs` (
	`id` text PRIMARY KEY NOT NULL,
	`plan_id` text NOT NULL,
	`project_id` text NOT NULL,
	`job_id` text,
	`state` text NOT NULL,
	`dry_run` integer DEFAULT 0 NOT NULL,
	`target_count` integer NOT NULL,
	`max_candidates` integer NOT NULL,
	`max_download_bytes` integer NOT NULL,
	`downloaded_count` integer DEFAULT 0 NOT NULL,
	`bytes_downloaded` integer DEFAULT 0 NOT NULL,
	`request_count` integer DEFAULT 0 NOT NULL,
	`cycle_count` integer DEFAULT 0 NOT NULL,
	`observed_yield` real DEFAULT 0 NOT NULL,
	`next_batch_size` integer DEFAULT 0 NOT NULL,
	`stop_reason` text,
	`error` text,
	`created_at` text NOT NULL,
	`updated_at` text NOT NULL,
	`completed_at` text,
	FOREIGN KEY (`plan_id`) REFERENCES `acquisition_plans`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`project_id`) REFERENCES `projects`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE INDEX `idx_acquisition_runs_project_created` ON `acquisition_runs` (`project_id`,`created_at`,`id`);--> statement-breakpoint
CREATE INDEX `idx_acquisition_runs_state_updated` ON `acquisition_runs` (`state`,`updated_at`);