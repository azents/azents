# CompactedEventRetentionUpdateRequest

Independent compacted-event retention mutation.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**expected_revision** | **int** |  | 
**compacted_event_retention_days** | **int** |  | 

## Example

```python
from azentsadminclient.models.compacted_event_retention_update_request import CompactedEventRetentionUpdateRequest

# TODO update the JSON string below
json = "{}"
# create an instance of CompactedEventRetentionUpdateRequest from a JSON string
compacted_event_retention_update_request_instance = CompactedEventRetentionUpdateRequest.from_json(json)
# print the JSON string representation of the object
print(CompactedEventRetentionUpdateRequest.to_json())

# convert the object into a dict
compacted_event_retention_update_request_dict = compacted_event_retention_update_request_instance.to_dict()
# create an instance of CompactedEventRetentionUpdateRequest from a dict
compacted_event_retention_update_request_from_dict = CompactedEventRetentionUpdateRequest.from_dict(compacted_event_retention_update_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


