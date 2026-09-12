# RuntimeWebActionErrorDetail

Bounded Public API control error detail.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**code** | **str** |  | 
**scope** | **str** |  | 

## Example

```python
from azentspublicclient.models.runtime_web_action_error_detail import RuntimeWebActionErrorDetail

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeWebActionErrorDetail from a JSON string
runtime_web_action_error_detail_instance = RuntimeWebActionErrorDetail.from_json(json)
# print the JSON string representation of the object
print(RuntimeWebActionErrorDetail.to_json())

# convert the object into a dict
runtime_web_action_error_detail_dict = runtime_web_action_error_detail_instance.to_dict()
# create an instance of RuntimeWebActionErrorDetail from a dict
runtime_web_action_error_detail_from_dict = RuntimeWebActionErrorDetail.from_dict(runtime_web_action_error_detail_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


