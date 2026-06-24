# ImageThumbnails

3-tier thumbnails for API response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**small** | [**ImageFile**](ImageFile.md) |  | [optional]
**medium** | [**ImageFile**](ImageFile.md) |  | [optional]
**large** | [**ImageFile**](ImageFile.md) |  | [optional]

## Example

```python
from azentspublicclient.models.image_thumbnails import ImageThumbnails

# TODO update the JSON string below
json = "{}"
# create an instance of ImageThumbnails from a JSON string
image_thumbnails_instance = ImageThumbnails.from_json(json)
# print the JSON string representation of the object
print(ImageThumbnails.to_json())

# convert the object into a dict
image_thumbnails_dict = image_thumbnails_instance.to_dict()
# create an instance of ImageThumbnails from a dict
image_thumbnails_from_dict = ImageThumbnails.from_dict(image_thumbnails_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
