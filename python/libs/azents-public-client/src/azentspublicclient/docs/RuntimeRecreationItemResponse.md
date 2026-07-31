# RuntimeRecreationItemResponse

One non-success recreation item detail.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**runtime_id** | **str** |  | 
**status** | [**RuntimeRecreationItemStatus**](RuntimeRecreationItemStatus.md) |  | 
**attempt** | **int** |  | 
**dispatched_generation** | **int** |  | 
**failure_code** | **str** |  | 
**failure_message** | **str** |  | 
**updated_at** | **datetime** |  | 

## Example

```python
from azentspublicclient.models.runtime_recreation_item_response import RuntimeRecreationItemResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeRecreationItemResponse from a JSON string
runtime_recreation_item_response_instance = RuntimeRecreationItemResponse.from_json(json)
# print the JSON string representation of the object
print(RuntimeRecreationItemResponse.to_json())

# convert the object into a dict
runtime_recreation_item_response_dict = runtime_recreation_item_response_instance.to_dict()
# create an instance of RuntimeRecreationItemResponse from a dict
runtime_recreation_item_response_from_dict = RuntimeRecreationItemResponse.from_dict(runtime_recreation_item_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


