# ElevateResponse

Elevation response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**access_token** | **str** | Elevated JWT access token |
**expires_in** | **int** | Access token expiration time (seconds) |

## Example

```python
from azentspublicclient.models.elevate_response import ElevateResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ElevateResponse from a JSON string
elevate_response_instance = ElevateResponse.from_json(json)
# print the JSON string representation of the object
print(ElevateResponse.to_json())

# convert the object into a dict
elevate_response_dict = elevate_response_instance.to_dict()
# create an instance of ElevateResponse from a dict
elevate_response_from_dict = ElevateResponse.from_dict(elevate_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
