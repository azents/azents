# GoogleFinalSettings

Complete final reviewed settings; no provider permission booleans accepted.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**name** | **str** |  | 
**slug** | **str** |  | 
**description** | **str** |  | 
**prompt** | **str** |  | 
**enabled** | **bool** |  | 
**always_expose_tools** | **bool** |  | 
**tasks** | [**List[GoogleTask]**](GoogleTask.md) |  | 
**timeout** | **float** |  | 
**security_risk_acknowledged** | **bool** |  | 

## Example

```python
from azentspublicclient.models.google_final_settings import GoogleFinalSettings

# TODO update the JSON string below
json = "{}"
# create an instance of GoogleFinalSettings from a JSON string
google_final_settings_instance = GoogleFinalSettings.from_json(json)
# print the JSON string representation of the object
print(GoogleFinalSettings.to_json())

# convert the object into a dict
google_final_settings_dict = google_final_settings_instance.to_dict()
# create an instance of GoogleFinalSettings from a dict
google_final_settings_from_dict = GoogleFinalSettings.from_dict(google_final_settings_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


