# BrowserFrameResponse


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**url** | **str** |  | 
**name** | **str** |  | 

## Example

```python
from azentspublicclient.models.browser_frame_response import BrowserFrameResponse

# TODO update the JSON string below
json = "{}"
# create an instance of BrowserFrameResponse from a JSON string
browser_frame_response_instance = BrowserFrameResponse.from_json(json)
# print the JSON string representation of the object
print(BrowserFrameResponse.to_json())

# convert the object into a dict
browser_frame_response_dict = browser_frame_response_instance.to_dict()
# create an instance of BrowserFrameResponse from a dict
browser_frame_response_from_dict = BrowserFrameResponse.from_dict(browser_frame_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


