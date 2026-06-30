# ImageFile

Single image for API response — resolved URL + resolution.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**url** | **str** | CDN URL or 1-hour presigned GET URL | 
**width** | **int** | Width pixels | 
**height** | **int** | Height pixels | 

## Example

```python
from azentspublicclient.models.image_file import ImageFile

# TODO update the JSON string below
json = "{}"
# create an instance of ImageFile from a JSON string
image_file_instance = ImageFile.from_json(json)
# print the JSON string representation of the object
print(ImageFile.to_json())

# convert the object into a dict
image_file_dict = image_file_instance.to_dict()
# create an instance of ImageFile from a dict
image_file_from_dict = ImageFile.from_dict(image_file_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


