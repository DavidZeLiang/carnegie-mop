import importlib
import json
import logging
import os
from typing import Any, Dict, List, Optional

import yaml
from pyraisdk.dynbatch import BaseModel, DynamicBatchModel

from base_model_wrapper import BaseModelWrapper, MopInferenceInput
from constant import CM_MODEL_WRAPPER_NAME, DYNAMIC_SETTINGS_YAML

try:
    inference_module = importlib.import_module(CM_MODEL_WRAPPER_NAME)
    ModelWrapper = [getattr(inference_module, i) for i in inference_module.__dict__.keys() if
                    hasattr(inference_module.__dict__.get(i), '__bases__')
                    and BaseModelWrapper in inference_module.__dict__.get(i).__bases__][0]
except Exception as e:
    result = str(e)
    logging.exception(result)
    raise e


class MOPInferenceWrapper:
    def __init__(self, base_model_wrapper: BaseModelWrapper) -> None:
        self.model_wrapper = base_model_wrapper

    def init(self, model_root: str) -> None:
        self.model_wrapper.init(model_root)

    def run(self, item: Dict, triggered_by_mop: False) -> Dict:
        if not triggered_by_mop:
            customized_output = self.model_wrapper.inference(item)
            return [customized_output]
        else:
            if isinstance(item, dict):
                mop_input = MopInferenceInput().from_dict(item)
                customized_input = self.model_wrapper.convert_mop_input_to_customized_input(mop_input)
                customized_output = self.model_wrapper.inference(customized_input)
                mop_output = self.model_wrapper.convert_customized_output_to_mop_output(customized_output)
                return mop_output.output

    def run_batch(self, items: List[dict], triggered_by_mop: False) -> List[dict]:
        if not triggered_by_mop:
            customized_outputs = self.model_wrapper.inference_batch(items)
            return customized_outputs
        else:
            customized_inputs = [
                self.model_wrapper.convert_mop_input_to_customized_input(MopInferenceInput().from_dict(item)) for item
                in
                items]

            customized_outputs = self.model_wrapper.inference_batch(customized_inputs)
            mop_outputs = [self.model_wrapper.convert_customized_output_to_mop_output(customized_output).output for
                           customized_output in customized_outputs]
            return mop_outputs


batch_model: Optional[DynamicBatchModel] = None
base_model_wrapper: BaseModelWrapper = ModelWrapper()
inference_wrapper: MOPInferenceWrapper = MOPInferenceWrapper(base_model_wrapper)
batch_size: Optional[int] = None


class WrapModel(BaseModel):
    def predict(self, items: List[Any], triggered_by_mop=False) -> List[Any]:
        return inference_wrapper.run_batch(items, triggered_by_mop, batch_size=batch_size)


def _get_dynamic_batch_args() -> Optional[Dict]:
    """ if dynamic batch not enable, return None
    """
    if not os.path.exists(DYNAMIC_SETTINGS_YAML):
        return None

    # load settings.yml
    with open(DYNAMIC_SETTINGS_YAML) as dynamic_settings_file:
        try:
            settings = yaml.safe_load(dynamic_settings_file)
        except yaml.YAMLError:
            raise Exception("Load Dynamic Setting Yaml Fail")

    # check enable
    dynamic_batch = settings.get('dynamicBatch', {})
    enable = dynamic_batch.get('enable', None)
    if enable is None:
        return None
    if not (isinstance(enable, bool) and enable):
        return None

    # get args
    args = {
        'max_batch_size': dynamic_batch.get('maxBatchSize'),
        'idle_batch_size': dynamic_batch.get('idleBatchSize'),
        'max_batch_interval': dynamic_batch.get('maxBatchInterval'),
    }
    return {k: v for k, v in args.items() if v is not None}


class NumpyJsonEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, np.bool_):
            return bool(obj)
        return json.JSONEncoder.default(self, obj)


def mop_init():
    global batch_model
    global batch_size
    inference_wrapper.init(os.path.join(os.getenv("AZUREML_MODEL_DIR"), "../model"))

    # assign batch_model is enabled
    dynamic_batch_args = _get_dynamic_batch_args()
    if dynamic_batch_args is not None:
        batch_model = DynamicBatchModel(WrapModel(), **dynamic_batch_args)
        batch_size = dynamic_batch_args.get('max_batch_size')


def mop_run(raw_data: any, triggered_by_mop) -> any:
    if batch_model is not None:
        inference_result = batch_model.predict(raw_data, triggered_by_mop if isinstance(raw_data, list) else [raw_data])
        return inference_result
    if isinstance(raw_data, dict):
        inference_result = inference_wrapper.run(raw_data, triggered_by_mop)
        return inference_result
    if isinstance(raw_data, list):
        inference_result = inference_wrapper.run_batch(raw_data, triggered_by_mop)
        return inference_result
    raise Exception("Invalid input data format")


def build_response(inference_result: any) -> any:
    if isinstance(inference_result, dict):
        output_str = json.dumps(inference_result, cls=NumpyJsonEncoder)
        return json.loads(output_str)
    if isinstance(inference_result, list):
        res = [item.__dict__ if hasattr(inference_result, '__dict__') else item for item in inference_result]
        output_str = json.dumps(res)
        return json.loads(output_str)
    if hasattr(inference_result, '__dict__'):
        output_str = json.dumps(inference_result.__dict__)
        return json.loads(output_str)
    return inference_result


if __name__ == "__main__":
    mop_init()
    data_dict = {"data": "354"}
    res = mop_run(data_dict, False)
    print(res)
    text_dict = {"text": "354"}
    res = mop_run(text_dict, True)
    print(res)
    text_dict = [{"text": "354"}]
    res = mop_run(text_dict, True)
    print(res)
