# RegisterPATRequest

PAT registration request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**token** | **str** | GitHub Personal Access Token |

## Example

```python
from azentspublicclient.models.register_pat_request import RegisterPATRequest

# TODO update the JSON string below
json = "{}"
# create an instance of RegisterPATRequest from a JSON string
register_pat_request_instance = RegisterPATRequest.from_json(json)
# print the JSON string representation of the object
print(RegisterPATRequest.to_json())

# convert the object into a dict
register_pat_request_dict = register_pat_request_instance.to_dict()
# create an instance of RegisterPATRequest from a dict
register_pat_request_from_dict = RegisterPATRequest.from_dict(register_pat_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
