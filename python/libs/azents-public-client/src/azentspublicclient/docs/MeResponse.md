# MeResponse

Current user information response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**email** | **str** | Primary email address |
**created_at** | **datetime** | Signup time |

## Example

```python
from azentspublicclient.models.me_response import MeResponse

# TODO update the JSON string below
json = "{}"
# create an instance of MeResponse from a JSON string
me_response_instance = MeResponse.from_json(json)
# print the JSON string representation of the object
print(MeResponse.to_json())

# convert the object into a dict
me_response_dict = me_response_instance.to_dict()
# create an instance of MeResponse from a dict
me_response_from_dict = MeResponse.from_dict(me_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


