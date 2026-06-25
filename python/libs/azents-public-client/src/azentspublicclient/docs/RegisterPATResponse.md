# RegisterPATResponse

PAT registration success response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**github_username** | **str** | GitHub username | 
**expires_at** | **datetime** |  | [optional] 

## Example

```python
from azentspublicclient.models.register_pat_response import RegisterPATResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RegisterPATResponse from a JSON string
register_pat_response_instance = RegisterPATResponse.from_json(json)
# print the JSON string representation of the object
print(RegisterPATResponse.to_json())

# convert the object into a dict
register_pat_response_dict = register_pat_response_instance.to_dict()
# create an instance of RegisterPATResponse from a dict
register_pat_response_from_dict = RegisterPATResponse.from_dict(register_pat_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


