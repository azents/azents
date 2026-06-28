# UploadedImage

Common response schema for uploaded image + thumbnails.  agent avatar, workspace icon, chat attachment preview, etc. all reuse this type. `default` is always non-null, so UI can safely render image with `default.url` even when all `thumbnails` are None.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**filename** | **str** | Original upload filename |
**default** | [**ImageFile**](ImageFile.md) | Always non-null fallback image |
**thumbnails** | [**ImageThumbnails**](ImageThumbnails.md) | Declarative 3-tier thumbnails |
**uploaded_at** | **datetime** | Upload completion time (ISO 8601, tz-aware) |

## Example

```python
from azentspublicclient.models.uploaded_image import UploadedImage

# TODO update the JSON string below
json = "{}"
# create an instance of UploadedImage from a JSON string
uploaded_image_instance = UploadedImage.from_json(json)
# print the JSON string representation of the object
print(UploadedImage.to_json())

# convert the object into a dict
uploaded_image_dict = uploaded_image_instance.to_dict()
# create an instance of UploadedImage from a dict
uploaded_image_from_dict = UploadedImage.from_dict(uploaded_image_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


