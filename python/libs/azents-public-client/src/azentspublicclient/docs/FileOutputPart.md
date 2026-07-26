# FileOutputPart

File part lowerable to LLM rich input.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** |  | [optional] [default to 'file']
**model_file_id** | **str** | ModelFile ID | 
**media_type** | **str** | MIME type | 
**name** | **str** |  | [optional] 
**size** | **int** |  | [optional] 
**kind** | **str** |  | [optional] 
**detail** | **str** |  | [optional] 
**caption** | **str** |  | [optional] 
**alt_text** | **str** |  | [optional] 
**metadata** | **Dict[str, str]** |  | [optional] 

## Example

```python
from azentspublicclient.models.file_output_part import FileOutputPart

# TODO update the JSON string below
json = "{}"
# create an instance of FileOutputPart from a JSON string
file_output_part_instance = FileOutputPart.from_json(json)
# print the JSON string representation of the object
print(FileOutputPart.to_json())

# convert the object into a dict
file_output_part_dict = file_output_part_instance.to_dict()
# create an instance of FileOutputPart from a dict
file_output_part_from_dict = FileOutputPart.from_dict(file_output_part_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


