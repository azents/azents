# SystemBootstrapStatusResponse

Initial system bootstrap availability response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**available** | **bool** | Whether initial bootstrap is available |

## Example

```python
from azentsadminclient.models.system_bootstrap_status_response import SystemBootstrapStatusResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SystemBootstrapStatusResponse from a JSON string
system_bootstrap_status_response_instance = SystemBootstrapStatusResponse.from_json(json)
# print the JSON string representation of the object
print(SystemBootstrapStatusResponse.to_json())

# convert the object into a dict
system_bootstrap_status_response_dict = system_bootstrap_status_response_instance.to_dict()
# create an instance of SystemBootstrapStatusResponse from a dict
system_bootstrap_status_response_from_dict = SystemBootstrapStatusResponse.from_dict(system_bootstrap_status_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
