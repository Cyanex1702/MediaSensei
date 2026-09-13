CREATE TABLE `assets` (
	`id` text PRIMARY KEY NOT NULL,
	`project_id` text NOT NULL,
	`source_id` text,
	`sha256` text NOT NULL,
	`original_filename` text NOT NULL,
	`media_type` text NOT NULL,
	`object_key` text NOT NULL,
	`byte_size` integer NOT NULL,
	`status` text DEFAULT 'active' NOT NULL,
	`quality_score` real,
	`metadata_json` text DEFAULT '{}' NOT NULL,
	`created_at` text NOT NULL,
	FOREIGN KEY (`project_id`) REFERENCES `projects`(`id`) ON UPDATE no action ON DELETE no action,
	FOREIGN KEY (`source_id`) REFERENCES `sources`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE INDEX `idx_assets_project_media` ON `assets` (`project_id`,`media_type`);--> statement-breakpoint
CREATE INDEX `idx_assets_sha256` ON `assets` (`sha256`);--> statement-breakpoint
CREATE INDEX `idx_assets_project_status` ON `assets` (`project_id`,`status`);--> statement-breakpoint
CREATE TABLE `content_units` (
	`id` text PRIMARY KEY NOT NULL,
	`asset_id` text NOT NULL,
	`kind` text NOT NULL,
	`locator_json` text DEFAULT '{}' NOT NULL,
	`text_content` text,
	`parent_id` text,
	`created_at` text NOT NULL,
	FOREIGN KEY (`asset_id`) REFERENCES `assets`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE INDEX `idx_content_units_asset_id` ON `content_units` (`asset_id`);--> statement-breakpoint
CREATE TABLE `dataset_versions` (
	`id` text PRIMARY KEY NOT NULL,
	`project_id` text NOT NULL,
	`version` integer NOT NULL,
	`manifest_hash` text NOT NULL,
	`sample_count` integer NOT NULL,
	`split_seed` integer NOT NULL,
	`created_at` text NOT NULL,
	FOREIGN KEY (`project_id`) REFERENCES `projects`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE INDEX `idx_dataset_versions_project` ON `dataset_versions` (`project_id`,`version`);--> statement-breakpoint
CREATE TABLE `jobs` (
	`id` text PRIMARY KEY NOT NULL,
	`project_id` text NOT NULL,
	`kind` text NOT NULL,
	`state` text NOT NULL,
	`progress` integer DEFAULT 0 NOT NULL,
	`checkpoint_json` text DEFAULT '{}' NOT NULL,
	`error_summary` text,
	`created_at` text NOT NULL,
	`updated_at` text NOT NULL,
	FOREIGN KEY (`project_id`) REFERENCES `projects`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE INDEX `idx_jobs_project_state` ON `jobs` (`project_id`,`state`);--> statement-breakpoint
CREATE TABLE `projects` (
	`id` text PRIMARY KEY NOT NULL,
	`name` text NOT NULL,
	`description` text DEFAULT '' NOT NULL,
	`data_policy` text DEFAULT 'local_only' NOT NULL,
	`created_at` text NOT NULL,
	`updated_at` text NOT NULL
);
--> statement-breakpoint
CREATE TABLE `sources` (
	`id` text PRIMARY KEY NOT NULL,
	`project_id` text NOT NULL,
	`kind` text NOT NULL,
	`uri` text,
	`revision` text,
	`metadata_json` text DEFAULT '{}' NOT NULL,
	`created_at` text NOT NULL,
	FOREIGN KEY (`project_id`) REFERENCES `projects`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE INDEX `idx_sources_project_id` ON `sources` (`project_id`);--> statement-breakpoint
CREATE TABLE `workspace_state` (
	`id` text PRIMARY KEY NOT NULL,
	`state_json` text NOT NULL,
	`updated_at` text NOT NULL
);
