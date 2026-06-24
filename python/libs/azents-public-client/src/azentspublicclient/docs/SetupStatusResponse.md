# SetupStatusResponse

Settings status response for the settings page.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**platform_linked** | **bool** | Whether platform account is linked |
**pat_registered** | **bool** | Whether PAT is registered |
**github_username** | **str** |  | [optional]

## Example

```python
from azentspublicclient.models.setup_status_response import SetupStatusResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SetupStatusResponse from a JSON string
setup_status_response_instance = SetupStatusResponse.from_json(json)
# print the JSON string representation of the object
print(SetupStatusResponse.to_json())

# convert the object into a dict
setup_status_response_dict = setup_status_response_instance.to_dict()
# create an instance of SetupStatusResponse from a dict
setup_status_response_from_dict = SetupStatusResponse.from_dict(setup_status_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
