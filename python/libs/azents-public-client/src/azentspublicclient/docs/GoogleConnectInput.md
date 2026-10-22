# GoogleConnectInput

Explicit service/scope intent before consent; requested scopes are not grants.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**services** | [**List[GoogleService]**](GoogleService.md) |  | 
**tool_groups** | [**List[GoogleToolGroup]**](GoogleToolGroup.md) |  | 
**oauth_request_scopes** | **List[str]** |  | 
**timeout** | **float** |  | 

## Example

```python
from azentspublicclient.models.google_connect_input import GoogleConnectInput

# TODO update the JSON string below
json = "{}"
# create an instance of GoogleConnectInput from a JSON string
google_connect_input_instance = GoogleConnectInput.from_json(json)
# print the JSON string representation of the object
print(GoogleConnectInput.to_json())

# convert the object into a dict
google_connect_input_dict = google_connect_input_instance.to_dict()
# create an instance of GoogleConnectInput from a dict
google_connect_input_from_dict = GoogleConnectInput.from_dict(google_connect_input_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


