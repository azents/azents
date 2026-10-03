# CatalogTimeWindow

UTC minute window with an independently scoped weekday calendar.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**start_minute** | **int** |  | 
**end_minute** | **int** |  | 
**weekdays** | **List[int]** |  | 

## Example

```python
from azentspublicclient.models.catalog_time_window import CatalogTimeWindow

# TODO update the JSON string below
json = "{}"
# create an instance of CatalogTimeWindow from a JSON string
catalog_time_window_instance = CatalogTimeWindow.from_json(json)
# print the JSON string representation of the object
print(CatalogTimeWindow.to_json())

# convert the object into a dict
catalog_time_window_dict = catalog_time_window_instance.to_dict()
# create an instance of CatalogTimeWindow from a dict
catalog_time_window_from_dict = CatalogTimeWindow.from_dict(catalog_time_window_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


