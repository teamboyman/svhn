import os
import numpy as np
import h5py
import random
import json
from PIL import Image
import tensorflow as tf
from meta import Meta

# tmp_datadir = '/notebooks/dataVolume/workspace/data'
tmp_datadir = '/home/amax/Documents/wit/data'
original_data_dir = './data'
tf.app.flags.DEFINE_string('data_dir', tmp_datadir,
                           'Directory to SVHN (format 1) folders and write the converted files')
FLAGS = tf.app.flags.FLAGS


class ExampleReader(object):
    def __init__(self, path_to_image_files):
        self._path_to_image_files = path_to_image_files
        self._num_examples = len(self._path_to_image_files)
        self._example_pointer = 0

    @staticmethod
    def _get_attrs(digit_struct_mat_file, index):
        """
        Returns a dictionary which contains keys: label, left, top, width and height, each key has multiple values.
        """
        attrs = {}
        f = digit_struct_mat_file
        item = f['digitStruct']['bbox'][index].item()
        for key in ['label', 'left', 'top', 'width', 'height']:
            attr = f[item][key]
            values = [f[attr.value[i].item()].value[0][0]
                      for i in range(len(attr))] if len(attr) > 1 else [attr.value[0][0]]
            attrs[key] = values
        return attrs

    @staticmethod
    def _get_attrs2(digit_struct_json_file, index):
        #print('index = '+ str(index))
        digit_struct_mat_file = digit_struct_json_file
        attrs = {}
        attrs['top'] = []
        attrs['left'] = []
        attrs['height'] = []
        attrs['width'] = []
        attrs['label'] = []
        def stringtoint(x):
            return {
                '0': 0,
                '1': 1,
                '2': 2,
                '3': 3,
                '4': 4,
                '5': 5,
                '6': 6,
                '7': 7,
                '8': 8,
                '9': 9,
                'A':10,
                'B':11,
                'C':12,
                'D':13,
                'E':14,
                'F':15,
                'G':16,
                'H':17,
                'I':18,
                'J':19,
                'K':20,
                'L':21,
                'M':22,
                'N':23,
                'O':24,
                'P':25,
                'Q':26,
                'R':27,
                'S':28,
                'T':29,
                'U':30,
                'V':31,
                'W':32,
                'X':33,
                'Y':34,
                'Z':35,
                '-':36
            }[x]
        #f = digit_struct_mat_file
        #print(digit_struct_mat_file['data'][index]['bbox'][0]['top'])
        #print(len(digit_struct_mat_file['data'][index]['bbox']))
        for i in range(len(digit_struct_mat_file['data'][index]['bbox'])):
            attrs['top'].append(float(digit_struct_mat_file['data'][index]['bbox'][i]['top']))
            attrs['left'].append(float(digit_struct_mat_file['data'][index]['bbox'][i]['left']))
            attrs['height'].append(float(digit_struct_mat_file['data'][index]['bbox'][i]['height']))
            attrs['width'].append(float(digit_struct_mat_file['data'][index]['bbox'][i]['width']))
            #attrs['label'].append(float(ord(digit_struct_mat_file['data'][index]['bbox'][i]['label'])))
            label = stringtoint(digit_struct_mat_file['data'][index]['bbox'][i]['label'])
            attrs['label'].append(label)
        #print(attrs)
        return attrs

    @staticmethod
    def _preprocess(image, bbox_left, bbox_top, bbox_width, bbox_height):
        cropped_left, cropped_top, cropped_width, cropped_height = (int(round(bbox_left - 0.15 * bbox_width)),
                                                                    int(round(bbox_top - 0.15 * bbox_height)),
                                                                    int(round(bbox_width * 1.3)),
                                                                    int(round(bbox_height * 1.3)))
        image = image.crop([cropped_left, cropped_top, cropped_left + cropped_width, cropped_top + cropped_height])
        image = image.resize([64, 64])
        return image



    def read_and_convert(self, digit_struct_mat_file):
        """
        Read and convert to example, returns None if no data is available.
        """
        if self._example_pointer == self._num_examples:
            return None
        path_to_image_file = self._path_to_image_files[self._example_pointer]
        index = int(path_to_image_file.split('\\')[-1].split('.')[0]) - 1
        self._example_pointer += 1

        attrs = ExampleReader._get_attrs2(digit_struct_mat_file, index)
        label_of_digits = attrs['label']
        length = len(label_of_digits)
        if length > 20:
            # skip this example
            return self.read_and_convert(digit_struct_mat_file)

        # the first digit 10 is the starting flag.
        # the seventh digit 11 is the ending flag.
        digits = [36, 37, 37, 37, 37, 37,37, 37, 37, 37, 37,37, 37, 37, 37, 37,37, 37, 37, 37, 37, 37]
        for idx, label_of_digit in enumerate(label_of_digits):
            digits[idx+1] = int(label_of_digit if label_of_digit != 36 else 0)    # label 10 is essentially digit zero

        attrs_left, attrs_top, attrs_width, attrs_height = map(lambda x: [int(i) for i in x], [attrs['left'], attrs['top'], attrs['width'], attrs['height']])
        min_left, min_top, max_right, max_bottom = (min(attrs_left),
                                                    min(attrs_top),
                                                    max(map(lambda x, y: x + y, attrs_left, attrs_width)),
                                                    max(map(lambda x, y: x + y, attrs_top, attrs_height)))
        center_x, center_y, max_side = ((min_left + max_right) / 2.0,
                                        (min_top + max_bottom) / 2.0,
                                        max(max_right - min_left, max_bottom - min_top))
        bbox_left, bbox_top, bbox_width, bbox_height = (center_x - max_side / 2.0,
                                                        center_y - max_side / 2.0,
                                                        max_side,
                                                        max_side)
        image = np.array(ExampleReader._preprocess(Image.open(path_to_image_file), bbox_left, bbox_top, bbox_width, bbox_height)).tobytes()

        example = tf.train.Example(features=tf.train.Features(feature={
            'image': tf.train.Feature(bytes_list=tf.train.BytesList(value=[image])),
            'length': tf.train.Feature(int64_list=tf.train.Int64List(value=[length])),
            'digits': tf.train.Feature(int64_list=tf.train.Int64List(value=digits))
        }))
        return example


def convert_to_tfrecords(path_to_dataset_dir_and_digit_struct_mat_file_tuples,
                         path_to_tfrecords_files, choose_writer_callback):
    num_examples = []
    writers = []

    for path_to_tfrecords_file in path_to_tfrecords_files:
        num_examples.append(0)
        writers.append(tf.python_io.TFRecordWriter(path_to_tfrecords_file))

    for path_to_dataset_dir, path_to_digit_struct_mat_file in path_to_dataset_dir_and_digit_struct_mat_file_tuples:
        path_to_image_files = tf.gfile.Glob(os.path.join(path_to_dataset_dir, '*.png'))
        total_files = len(path_to_image_files)
        print('%d files found in %s' % (total_files, path_to_dataset_dir))

        with open(path_to_digit_struct_mat_file, 'r') as digit_struct_mat_file:
            digit_struct_mat_file = json.load(digit_struct_mat_file)
            example_reader = ExampleReader(path_to_image_files)
            for index, path_to_image_file in enumerate(path_to_image_files):
                print('(%d/%d) processing %s' % (index + 1, total_files, path_to_image_file))

                example = example_reader.read_and_convert(digit_struct_mat_file)
                if example is None:
                    break

                idx = choose_writer_callback(path_to_tfrecords_files)
                writers[idx].write(example.SerializeToString())
                num_examples[idx] += 1

    for writer in writers:
        writer.close()

    return num_examples


def create_tfrecords_meta_file(num_train_examples, num_val_examples, num_test_examples,
                               path_to_tfrecords_meta_file):
    print('Saving meta file to %s...' % path_to_tfrecords_meta_file)
    meta = Meta()
    meta.num_train_examples = num_train_examples
    meta.num_val_examples = num_val_examples
    meta.num_test_examples = num_test_examples
    meta.save(path_to_tfrecords_meta_file)


def main(_):
    path_to_train_dir = os.path.join(FLAGS.data_dir, 'train')
    path_to_test_dir = os.path.join(FLAGS.data_dir, 'test')
    path_to_extra_dir = os.path.join(FLAGS.data_dir, 'extra')
    path_to_train_digit_struct_mat_file = os.path.join(path_to_train_dir, 'digitStruct.json')
    path_to_test_digit_struct_mat_file = os.path.join(path_to_test_dir, 'digitStruct.json')
    path_to_extra_digit_struct_mat_file = os.path.join(path_to_extra_dir, 'digitStruct.json')

    path_to_train_tfrecords_file = os.path.join(FLAGS.data_dir, 'train.tfrecords')
    path_to_val_tfrecords_file = os.path.join(FLAGS.data_dir, 'val.tfrecords')
    path_to_test_tfrecords_file = os.path.join(FLAGS.data_dir, 'test.tfrecords')
    path_to_tfrecords_meta_file = os.path.join(FLAGS.data_dir, 'meta.json')

    for path_to_file in [path_to_train_tfrecords_file, path_to_val_tfrecords_file, path_to_test_tfrecords_file]:
        assert not os.path.exists(path_to_file), 'The file %s already exists' % path_to_file

    print('Processing training and validation data...')
    [num_train_examples, num_val_examples] = convert_to_tfrecords([(path_to_train_dir, path_to_train_digit_struct_mat_file),
                                                                   (path_to_extra_dir, path_to_extra_digit_struct_mat_file)],
                                                                  [path_to_train_tfrecords_file, path_to_val_tfrecords_file],
                                                                  lambda paths: 0 if random.random() > 0.1 else 1)
    print('Processing test data...')
    [num_test_examples] = convert_to_tfrecords([(path_to_test_dir, path_to_test_digit_struct_mat_file)],
                                               [path_to_test_tfrecords_file],
                                               lambda paths: 0)

    create_tfrecords_meta_file(num_train_examples, num_val_examples, num_test_examples,
                               path_to_tfrecords_meta_file)

    print('Done')


if __name__ == '__main__':
    tf.app.run(main=main)
