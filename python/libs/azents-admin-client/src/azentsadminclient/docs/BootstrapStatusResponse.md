# BootstrapStatusResponse

First owner bootstrap status response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**available** | **bool** | bootstrap availability flag |

## Example

```python
from azentsadminclient.models.bootstrap_status_response import BootstrapStatusResponse

# TODO update the JSON string below
json = "{}"
# create an instance of BootstrapStatusResponse from a JSON string
bootstrap_status_response_instance = BootstrapStatusResponse.from_json(json)
# print the JSON string representation of the object
print(BootstrapStatusResponse.to_json())

# convert the object into a dict
bootstrap_status_response_dict = bootstrap_status_response_instance.to_dict()
# create an instance of BootstrapStatusResponse from a dict
bootstrap_status_response_from_dict = BootstrapStatusResponse.from_dict(bootstrap_status_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
