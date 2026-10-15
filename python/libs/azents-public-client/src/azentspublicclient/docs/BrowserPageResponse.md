# BrowserPageResponse


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**task_id** | **str** |  | 
**resource_incarnation** | **str** |  | 
**url** | **str** |  | 
**title** | **str** |  | 
**frames** | [**List[BrowserFrameResponse]**](BrowserFrameResponse.md) |  | 

## Example

```python
from azentspublicclient.models.browser_page_response import BrowserPageResponse

# TODO update the JSON string below
json = "{}"
# create an instance of BrowserPageResponse from a JSON string
browser_page_response_instance = BrowserPageResponse.from_json(json)
# print the JSON string representation of the object
print(BrowserPageResponse.to_json())

# convert the object into a dict
browser_page_response_dict = browser_page_response_instance.to_dict()
# create an instance of BrowserPageResponse from a dict
browser_page_response_from_dict = BrowserPageResponse.from_dict(browser_page_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


