from mediasensei_plugin_sdk import PluginManifest, PluginRegistration

MANIFEST = PluginManifest(
    name="example-metadata-analyzer",
    version="0.2.0",
    api=">=1.5,<2",
    capabilities=("analyzer",),
    permissions=("read_asset_metadata",),
    license="Apache-2.0",
)


class ExampleMetadataAnalyzer:
    manifest = MANIFEST

    def analyze(self, object_key: str, parameters: dict[str, object]) -> dict[str, object]:
        return {"object_key": object_key, "parameter_count": len(parameters)}


PLUGIN = PluginRegistration(
    manifest=MANIFEST,
    analyzers=(ExampleMetadataAnalyzer(),),
)
