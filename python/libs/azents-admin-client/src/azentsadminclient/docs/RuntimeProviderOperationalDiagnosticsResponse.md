# RuntimeProviderOperationalDiagnosticsResponse

Active-generation Provider diagnostics or explicit unavailability.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**available** | **bool** |  | 
**generation** | **int** |  | 
**protocol_version** | **str** |  | 
**checked_at** | **datetime** |  | 
**warnings** | [**List[RuntimeProviderOperationalWarningResponse]**](RuntimeProviderOperationalWarningResponse.md) |  | 

## Example

```python
from azentsadminclient.models.runtime_provider_operational_diagnostics_response import RuntimeProviderOperationalDiagnosticsResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeProviderOperationalDiagnosticsResponse from a JSON string
runtime_provider_operational_diagnostics_response_instance = RuntimeProviderOperationalDiagnosticsResponse.from_json(json)
# print the JSON string representation of the object
print(RuntimeProviderOperationalDiagnosticsResponse.to_json())

# convert the object into a dict
runtime_provider_operational_diagnostics_response_dict = runtime_provider_operational_diagnostics_response_instance.to_dict()
# create an instance of RuntimeProviderOperationalDiagnosticsResponse from a dict
runtime_provider_operational_diagnostics_response_from_dict = RuntimeProviderOperationalDiagnosticsResponse.from_dict(runtime_provider_operational_diagnostics_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


