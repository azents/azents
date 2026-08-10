# AgentRuntimeRemovalProgressResponse

Bounded durable Runtime removal progress.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**status** | [**AgentRuntimeRemovalStatus**](AgentRuntimeRemovalStatus.md) |  | 
**stage** | [**AgentRuntimeRemovalStage**](AgentRuntimeRemovalStage.md) |  | 
**confirmed_at** | **datetime** |  | 
**cleanup_scanned_context_count** | **int** |  | 
**cleanup_invalidated_context_count** | **int** |  | 
**product_cleanup_completed_at** | **datetime** |  | 
**physical_deletion_required** | **bool** |  | 
**physical_delete_requested_at** | **datetime** |  | 
**physical_delete_acknowledgement_kind** | [**RuntimeTerminalDeleteAcknowledgementKind**](RuntimeTerminalDeleteAcknowledgementKind.md) |  | 
**physical_delete_acknowledged_at** | **datetime** |  | 
**attempt_count** | **int** |  | 
**next_attempt_at** | **datetime** |  | 
**last_error_kind** | **str** |  | 
**last_error_summary** | **str** |  | 
**started_at** | **datetime** |  | 
**completed_at** | **datetime** |  | 
**updated_at** | **datetime** |  | 

## Example

```python
from azentspublicclient.models.agent_runtime_removal_progress_response import AgentRuntimeRemovalProgressResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentRuntimeRemovalProgressResponse from a JSON string
agent_runtime_removal_progress_response_instance = AgentRuntimeRemovalProgressResponse.from_json(json)
# print the JSON string representation of the object
print(AgentRuntimeRemovalProgressResponse.to_json())

# convert the object into a dict
agent_runtime_removal_progress_response_dict = agent_runtime_removal_progress_response_instance.to_dict()
# create an instance of AgentRuntimeRemovalProgressResponse from a dict
agent_runtime_removal_progress_response_from_dict = AgentRuntimeRemovalProgressResponse.from_dict(agent_runtime_removal_progress_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


