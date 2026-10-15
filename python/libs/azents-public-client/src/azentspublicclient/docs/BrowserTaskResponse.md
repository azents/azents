# BrowserTaskResponse


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**label** | **str** |  | 
**resource_incarnation** | **str** |  | 
**pages** | [**List[BrowserPageResponse]**](BrowserPageResponse.md) |  | 

## Example

```python
from azentspublicclient.models.browser_task_response import BrowserTaskResponse

# TODO update the JSON string below
json = "{}"
# create an instance of BrowserTaskResponse from a JSON string
browser_task_response_instance = BrowserTaskResponse.from_json(json)
# print the JSON string representation of the object
print(BrowserTaskResponse.to_json())

# convert the object into a dict
browser_task_response_dict = browser_task_response_instance.to_dict()
# create an instance of BrowserTaskResponse from a dict
browser_task_response_from_dict = BrowserTaskResponse.from_dict(browser_task_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


