# ScheduledTaskCurrentCycleEnvelope

Nullable current cycle for one Task.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**current_cycle** | [**ScheduledTaskCurrentCycleResponse**](ScheduledTaskCurrentCycleResponse.md) |  | 

## Example

```python
from azentspublicclient.models.scheduled_task_current_cycle_envelope import ScheduledTaskCurrentCycleEnvelope

# TODO update the JSON string below
json = "{}"
# create an instance of ScheduledTaskCurrentCycleEnvelope from a JSON string
scheduled_task_current_cycle_envelope_instance = ScheduledTaskCurrentCycleEnvelope.from_json(json)
# print the JSON string representation of the object
print(ScheduledTaskCurrentCycleEnvelope.to_json())

# convert the object into a dict
scheduled_task_current_cycle_envelope_dict = scheduled_task_current_cycle_envelope_instance.to_dict()
# create an instance of ScheduledTaskCurrentCycleEnvelope from a dict
scheduled_task_current_cycle_envelope_from_dict = ScheduledTaskCurrentCycleEnvelope.from_dict(scheduled_task_current_cycle_envelope_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


