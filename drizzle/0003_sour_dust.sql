CREATE TABLE `tabular_analysis` (
	`analysis_key` text PRIMARY KEY NOT NULL,
	`source_sha256` text NOT NULL,
	`source_format` text NOT NULL,
	`normalized_sha256` text NOT NULL,
	`normalized_object_key` text NOT NULL,
	`row_count` integer NOT NULL,
	`column_count` integer NOT NULL,
	`schema_json` text NOT NULL,
	`profile_json` text NOT NULL,
	`options_json` text DEFAULT '{}' NOT NULL,
	`updated_at` text NOT NULL
);
--> statement-breakpoint
CREATE INDEX `idx_tabular_analysis_source` ON `tabular_analysis` (`source_sha256`,`source_format`);--> statement-breakpoint
CREATE TABLE `tabular_datasets` (
	`id` text PRIMARY KEY NOT NULL,
	`project_id` text NOT NULL,
	`asset_id` text NOT NULL,
	`analysis_key` text NOT NULL,
	`name` text NOT NULL,
	`schema_mapping_json` text DEFAULT '{}' NOT NULL,
	`custom_metadata_json` text DEFAULT '{}' NOT NULL,
	`created_at` text NOT NULL,
	`updated_at` text NOT NULL,
	FOREIGN KEY (`project_id`) REFERENCES `projects`(`id`) ON UPDATE no action ON DELETE no action,
	FOREIGN KEY (`asset_id`) REFERENCES `assets`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE UNIQUE INDEX `idx_tabular_datasets_project_asset` ON `tabular_datasets` (`project_id`,`asset_id`);--> statement-breakpoint
CREATE INDEX `idx_tabular_datasets_project_created` ON `tabular_datasets` (`project_id`,`created_at`);--> statement-breakpoint
CREATE TABLE `tabular_exports` (
	`id` text PRIMARY KEY NOT NULL,
	`dataset_id` text NOT NULL,
	`format` text NOT NULL,
	`path` text NOT NULL,
	`sha256` text NOT NULL,
	`row_count` integer NOT NULL,
	`column_count` integer NOT NULL,
	`created_at` text NOT NULL,
	FOREIGN KEY (`dataset_id`) REFERENCES `tabular_datasets`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE INDEX `idx_tabular_exports_dataset_created` ON `tabular_exports` (`dataset_id`,`created_at`);--> statement-breakpoint
CREATE TABLE `tabular_queries` (
	`id` text PRIMARY KEY NOT NULL,
	`dataset_id` text NOT NULL,
	`query_json` text NOT NULL,
	`row_count` integer NOT NULL,
	`duration_ms` real NOT NULL,
	`created_at` text NOT NULL,
	FOREIGN KEY (`dataset_id`) REFERENCES `tabular_datasets`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE INDEX `idx_tabular_queries_dataset_created` ON `tabular_queries` (`dataset_id`,`created_at`);