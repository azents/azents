# ManagedBlock


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**agent_id** | **str** |  | 
**principal_id** | **str** |  | 
**principal_label** | **str** |  | 
**reason** | **str** |  | 
**created_at** | **datetime** |  | 
**removed_at** | **datetime** |  | 

## Example

```python
from azentspublicclient.models.managed_block import ManagedBlock

# TODO update the JSON string below
json = "{}"
# create an instance of ManagedBlock from a JSON string
managed_block_instance = ManagedBlock.from_json(json)
# print the JSON string representation of the object
print(ManagedBlock.to_json())

# convert the object into a dict
managed_block_dict = managed_block_instance.to_dict()
# create an instance of ManagedBlock from a dict
managed_block_from_dict = ManagedBlock.from_dict(managed_block_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


