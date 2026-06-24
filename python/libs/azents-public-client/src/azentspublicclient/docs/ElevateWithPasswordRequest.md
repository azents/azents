# ElevateWithPasswordRequest

Password elevation request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**password** | **str** | Password |

## Example

```python
from azentspublicclient.models.elevate_with_password_request import ElevateWithPasswordRequest

# TODO update the JSON string below
json = "{}"
# create an instance of ElevateWithPasswordRequest from a JSON string
elevate_with_password_request_instance = ElevateWithPasswordRequest.from_json(json)
# print the JSON string representation of the object
print(ElevateWithPasswordRequest.to_json())

# convert the object into a dict
elevate_with_password_request_dict = elevate_with_password_request_instance.to_dict()
# create an instance of ElevateWithPasswordRequest from a dict
elevate_with_password_request_from_dict = ElevateWithPasswordRequest.from_dict(elevate_with_password_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
