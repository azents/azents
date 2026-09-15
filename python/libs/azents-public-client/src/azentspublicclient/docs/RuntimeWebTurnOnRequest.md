# RuntimeWebTurnOnRequest

Turn an Off service On, optionally selecting duration atomically.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**expected_revision** | **int** |  | 
**operation_key** | **str** |  | 
**selected_duration_seconds** | **int** |  | [optional] 

## Example

```python
from azentspublicclient.models.runtime_web_turn_on_request import RuntimeWebTurnOnRequest

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeWebTurnOnRequest from a JSON string
runtime_web_turn_on_request_instance = RuntimeWebTurnOnRequest.from_json(json)
# print the JSON string representation of the object
print(RuntimeWebTurnOnRequest.to_json())

# convert the object into a dict
runtime_web_turn_on_request_dict = runtime_web_turn_on_request_instance.to_dict()
# create an instance of RuntimeWebTurnOnRequest from a dict
runtime_web_turn_on_request_from_dict = RuntimeWebTurnOnRequest.from_dict(runtime_web_turn_on_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


