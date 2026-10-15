# BrowserClosePageRequest


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**task_id** | **str** |  | 
**resource_incarnation** | **str** |  | 

## Example

```python
from azentspublicclient.models.browser_close_page_request import BrowserClosePageRequest

# TODO update the JSON string below
json = "{}"
# create an instance of BrowserClosePageRequest from a JSON string
browser_close_page_request_instance = BrowserClosePageRequest.from_json(json)
# print the JSON string representation of the object
print(BrowserClosePageRequest.to_json())

# convert the object into a dict
browser_close_page_request_dict = browser_close_page_request_instance.to_dict()
# create an instance of BrowserClosePageRequest from a dict
browser_close_page_request_from_dict = BrowserClosePageRequest.from_dict(browser_close_page_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


