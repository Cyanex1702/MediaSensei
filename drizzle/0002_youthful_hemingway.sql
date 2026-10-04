CREATE TABLE `dataset_exports` (
	`id` text PRIMARY KEY NOT NULL,
	`project_id` text NOT NULL,
	`exporter_id` text NOT NULL,
	`path` text NOT NULL,
	`manifest_hash` text NOT NULL,
	`sample_count` integer NOT NULL,
	`split_counts_json` text NOT NULL,
	`created_at` text NOT NULL,
	FOREIGN KEY (`project_id`) REFERENCES `projects`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE INDEX `idx_dataset_exports_project_created` ON `dataset_exports` (`project_id`,`created_at`);--> statement-breakpoint
CREATE TABLE `dataset_samples` (
	`id` text PRIMARY KEY NOT NULL,
	`project_id` text NOT NULL,
	`asset_id` text NOT NULL,
	`label` text DEFAULT 'unlabeled' NOT NULL,
	`split` text,
	`source_key` text,
	`group_key` text,
	`split_seed` integer,
	`split_strategy` text,
	`created_at` text NOT NULL,
	`updated_at` text NOT NULL,
	FOREIGN KEY (`project_id`) REFERENCES `projects`(`id`) ON UPDATE no action ON DELETE no action,
	FOREIGN KEY (`asset_id`) REFERENCES `assets`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE UNIQUE INDEX `idx_dataset_samples_project_asset` ON `dataset_samples` (`project_id`,`asset_id`);--> statement-breakpoint
CREATE INDEX `idx_dataset_samples_project_split` ON `dataset_samples` (`project_id`,`split`);--> statement-breakpoint
CREATE TABLE `derived_images` (
	`id` text PRIMARY KEY NOT NULL,
	`source_sha256` text NOT NULL,
	`sha256` text NOT NULL,
	`object_key` text NOT NULL,
	`kind` text NOT NULL,
	`format` text NOT NULL,
	`width` integer NOT NULL,
	`height` integer NOT NULL,
	`parameters_json` text NOT NULL,
	`parameters_hash` text NOT NULL,
	`created_at` text NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `idx_derived_images_source_kind_parameters` ON `derived_images` (`source_sha256`,`kind`,`parameters_hash`);--> statement-breakpoint
CREATE INDEX `idx_derived_images_source` ON `derived_images` (`source_sha256`,`kind`);--> statement-breakpoint
CREATE TABLE `duplicate_group_members` (
	`group_id` text NOT NULL,
	`asset_id` text NOT NULL,
	PRIMARY KEY(`group_id`, `asset_id`),
	FOREIGN KEY (`group_id`) REFERENCES `duplicate_groups`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`asset_id`) REFERENCES `assets`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE TABLE `duplicate_groups` (
	`id` text PRIMARY KEY NOT NULL,
	`project_id` text NOT NULL,
	`method` text NOT NULL,
	`group_key` text NOT NULL,
	`canonical_asset_id` text,
	`maximum_distance` integer DEFAULT 0 NOT NULL,
	`created_at` text NOT NULL,
	FOREIGN KEY (`project_id`) REFERENCES `projects`(`id`) ON UPDATE no action ON DELETE no action,
	FOREIGN KEY (`canonical_asset_id`) REFERENCES `assets`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE INDEX `idx_duplicate_groups_project_method` ON `duplicate_groups` (`project_id`,`method`);--> statement-breakpoint
CREATE TABLE `image_analysis` (
	`sha256` text PRIMARY KEY NOT NULL,
	`valid` integer NOT NULL,
	`format` text,
	`mime_type` text,
	`width` integer,
	`height` integer,
	`color_mode` text,
	`exif_orientation` integer,
	`has_alpha` integer DEFAULT false NOT NULL,
	`perceptual_hash` text,
	`blur_score` real,
	`quality_score` real,
	`error` text,
	`ocr_json` text,
	`updated_at` text NOT NULL
);
--> statement-breakpoint
CREATE INDEX `idx_image_analysis_phash` ON `image_analysis` (`perceptual_hash`);--> statement-breakpoint
CREATE TABLE `leakage_issues` (
	`id` text PRIMARY KEY NOT NULL,
	`project_id` text NOT NULL,
	`left_asset_id` text NOT NULL,
	`right_asset_id` text NOT NULL,
	`left_split` text NOT NULL,
	`right_split` text NOT NULL,
	`kind` text NOT NULL,
	`distance` integer NOT NULL,
	`created_at` text NOT NULL,
	FOREIGN KEY (`project_id`) REFERENCES `projects`(`id`) ON UPDATE no action ON DELETE no action,
	FOREIGN KEY (`left_asset_id`) REFERENCES `assets`(`id`) ON UPDATE no action ON DELETE no action,
	FOREIGN KEY (`right_asset_id`) REFERENCES `assets`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE UNIQUE INDEX `idx_leakage_issues_pair_kind` ON `leakage_issues` (`project_id`,`left_asset_id`,`right_asset_id`,`kind`);--> statement-breakpoint
CREATE INDEX `idx_leakage_issues_project_kind` ON `leakage_issues` (`project_id`,`kind`);