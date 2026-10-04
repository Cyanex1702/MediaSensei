CREATE TABLE `provider_import_files` (
	`import_id` text NOT NULL,
	`relative_path` text NOT NULL,
	`byte_size` integer,
	`expected_sha256` text,
	`etag` text,
	`state` text DEFAULT 'pending' NOT NULL,
	`asset_id` text,
	`actual_sha256` text,
	`object_key` text,
	`error` text,
	`metadata_json` text DEFAULT '{}' NOT NULL,
	`created_at` text NOT NULL,
	`updated_at` text NOT NULL,
	PRIMARY KEY(`import_id`, `relative_path`),
	FOREIGN KEY (`import_id`) REFERENCES `provider_imports`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`asset_id`) REFERENCES `assets`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE INDEX `idx_provider_import_files_import_state` ON `provider_import_files` (`import_id`,`state`);--> statement-breakpoint
CREATE TABLE `provider_imports` (
	`id` text PRIMARY KEY NOT NULL,
	`project_id` text NOT NULL,
	`source_id` text,
	`provider_id` text NOT NULL,
	`provider_version` text,
	`dataset_id` text NOT NULL,
	`requested_revision` text,
	`resolved_revision` text,
	`source_uri` text,
	`title` text,
	`license` text,
	`state` text NOT NULL,
	`allow_patterns_json` text DEFAULT '[]' NOT NULL,
	`ignore_patterns_json` text DEFAULT '[]' NOT NULL,
	`max_files` integer NOT NULL,
	`max_file_bytes` integer NOT NULL,
	`max_total_bytes` integer NOT NULL,
	`file_count` integer DEFAULT 0 NOT NULL,
	`filtered_count` integer DEFAULT 0 NOT NULL,
	`imported_count` integer DEFAULT 0 NOT NULL,
	`skipped_count` integer DEFAULT 0 NOT NULL,
	`failed_count` integer DEFAULT 0 NOT NULL,
	`imported_bytes` integer DEFAULT 0 NOT NULL,
	`manifest_hash` text,
	`error` text,
	`metadata_json` text DEFAULT '{}' NOT NULL,
	`created_at` text NOT NULL,
	`updated_at` text NOT NULL,
	FOREIGN KEY (`project_id`) REFERENCES `projects`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`source_id`) REFERENCES `sources`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE INDEX `idx_provider_imports_project_created` ON `provider_imports` (`project_id`,`created_at`,`id`);--> statement-breakpoint
CREATE INDEX `idx_provider_imports_provider_dataset_revision` ON `provider_imports` (`provider_id`,`dataset_id`,`resolved_revision`);