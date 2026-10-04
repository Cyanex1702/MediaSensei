CREATE TABLE `derived_media` (
	`id` text PRIMARY KEY NOT NULL,
	`source_sha256` text NOT NULL,
	`sha256` text NOT NULL,
	`object_key` text NOT NULL,
	`kind` text NOT NULL,
	`format` text NOT NULL,
	`mime_type` text NOT NULL,
	`parameters_json` text NOT NULL,
	`parameters_hash` text NOT NULL,
	`duration_seconds` real,
	`tool_revision` text,
	`created_at` text NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `idx_derived_media_source_kind_parameters` ON `derived_media` (`source_sha256`,`kind`,`parameters_hash`);--> statement-breakpoint
CREATE INDEX `idx_derived_media_source_kind` ON `derived_media` (`source_sha256`,`kind`);--> statement-breakpoint
CREATE TABLE `media_analysis` (
	`sha256` text PRIMARY KEY NOT NULL,
	`valid` integer NOT NULL,
	`media_kind` text NOT NULL,
	`container` text,
	`duration_seconds` real,
	`bit_rate` integer,
	`size_bytes` integer,
	`video_codec` text,
	`width` integer,
	`height` integer,
	`fps` real,
	`pixel_format` text,
	`audio_codec` text,
	`sample_rate` integer,
	`channels` integer,
	`channel_layout` text,
	`tags_json` text DEFAULT '{}' NOT NULL,
	`tool_revision` text,
	`error` text,
	`updated_at` text NOT NULL
);
--> statement-breakpoint
CREATE INDEX `idx_media_analysis_kind_valid` ON `media_analysis` (`media_kind`,`valid`);