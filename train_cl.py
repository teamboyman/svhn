import argparse
import os
from datetime import datetime
import time

import tensorflow as tf
from inputs import Inputs
from model import Model
from meta import Meta
from evaluator import Evaluator

# tf.app.flags.DEFINE_string(
#     'data_dir', './data', 'Directory to read TFRecords files')
# tf.app.flags.DEFINE_string(
#     'train_logdir', './logs/train', 'Directory to write training logs')
tf.app.flags.DEFINE_string('restore_checkpoint', None,
                           'Path to restore checkpoint (without postfix), e.g. ./logs/train/model.ckpt-100')
tf.app.flags.DEFINE_integer('batch_size', 32, 'Default 32')
tf.app.flags.DEFINE_float('learning_rate', 1e-2, 'Default 1e-2')
tf.app.flags.DEFINE_integer(
    'patience', 100, 'Default 100, set -1 to train infinitely')
tf.app.flags.DEFINE_integer('decay_steps', 10000, 'Default 10000')
tf.app.flags.DEFINE_float('decay_rate', 0.9, 'Default 0.9')
FLAGS = tf.app.flags.FLAGS


def _train(path_to_train_tfrecords_file, num_train_examples,
           path_to_val_tfrecords_file, num_val_examples,
           path_to_train_log_dir, path_to_restore_checkpoint_file,
           training_options):

    batch_size = training_options['batch_size']  # 32
    initial_patience = training_options['patience']  # 100
    # output information setting
    num_steps_to_show_loss = 100
    num_steps_to_check = 1000

    with tf.Graph().as_default():
        input_ops = Inputs(path_to_tfrecords_file=path_to_train_tfrecords_file,
                           batch_size=32,
                           shuffle=True,
                           # int(0.4 * num_train_examples)
                           min_queue_examples=5000,
                           num_preprocess_threads=4,
                           num_reader_threads=1)
        images, input_seqs, target_seqs, mask = input_ops.build_batch()

        mymodel = Model(vocab_size=39,
                        mode='train',
                        embedding_size=512,
                        num_lstm_units=64,
                        lstm_dropout_keep_prob=0.7,
                        cnn_drop_rate=0.2,
                        initializer_scale=0.08)

        logits = mymodel.inference(images, input_seqs, mask)

        total_loss = mymodel.loss(logits, target_seqs)

        global_step = tf.Variable(initial_value=0,
                                  name="global_step",
                                  trainable=False,
                                  collections=[tf.GraphKeys.GLOBAL_STEP, tf.GraphKeys.GLOBAL_VARIABLES])

        initial_learning_rate = training_options['learning_rate']  # 1e-2
        decay_steps = training_options['decay_steps']  # 10000
        decay_rate = training_options['decay_rate']  # 0.9

        learning_rate = tf.train.exponential_decay(initial_learning_rate,
                                                   global_step=global_step,
                                                   decay_steps=decay_steps,
                                                   decay_rate=decay_rate,
                                                   staircase=True)
        optimizer = tf.train.GradientDescentOptimizer(learning_rate)
        train_op = optimizer.minimize(total_loss, global_step=global_step)

        tf.summary.image('image', images)
        tf.summary.scalar('loss', total_loss)
        tf.summary.scalar('learning_rate', learning_rate)
        summary = tf.summary.merge_all()

        with tf.Session() as sess:
            summary_writer = tf.summary.FileWriter(
                path_to_train_log_dir, sess.graph)
            evaluator = Evaluator(os.path.join(
                path_to_train_log_dir, 'eval/val'))

            sess.run(tf.global_variables_initializer())
            sess.run(tf.local_variables_initializer())

            coord = tf.train.Coordinator()
            threads = tf.train.start_queue_runners(sess=sess, coord=coord)

            saver = tf.train.Saver()
            if path_to_restore_checkpoint_file is not None:
                assert tf.train.checkpoint_exists(path_to_restore_checkpoint_file), \
                    '%s not found' % path_to_restore_checkpoint_file
                saver.restore(sess, path_to_restore_checkpoint_file)
                print('Model restored from file: %s' %
                      path_to_restore_checkpoint_file)

            print('Start training')
            patience = initial_patience
            best_accuracy = 0.0
            duration = 0.0

            while True:
                start_time = time.time()
                _, loss_val, summary_val, global_step_val, learning_rate_val = sess.run(
                    [train_op, total_loss, summary, global_step, learning_rate])
                duration += time.time() - start_time

                if global_step_val % num_steps_to_show_loss == 0:
                    examples_per_sec = batch_size * num_steps_to_show_loss / duration
                    duration = 0.0
                    print('=> %s: step %d, loss = %f (%.1f examples/sec)' %
                          (datetime.now(), global_step_val, loss_val, examples_per_sec))

                if global_step_val % num_steps_to_check != 0:
                    continue

                summary_writer.add_summary(
                    summary_val, global_step=global_step_val)

                print('=> Evaluating on validation dataset...')
                path_to_latest_checkpoint_file = saver.save(
                    sess, os.path.join(path_to_train_log_dir, 'latest.ckpt'))
                accuracy = evaluator.evaluate(path_to_latest_checkpoint_file, path_to_val_tfrecords_file,
                                              num_val_examples,  # 23508
                                              global_step_val)
                print('==> accuracy = %f, best accuracy %f' %
                      (accuracy, best_accuracy))

                if accuracy > best_accuracy:
                    path_to_checkpoint_file = saver.save(sess, os.path.join(path_to_train_log_dir, 'model.ckpt'),
                                                         global_step=global_step_val)
                    print('=> Model saved to file: %s' %
                          path_to_checkpoint_file)
                    patience = initial_patience
                    best_accuracy = accuracy
                else:
                    patience -= 1

                print('=> patience = %d' % patience)
                if patience == 0:
                    break

            coord.request_stop()
            coord.join(threads)
            print('Finished')


def main(unused_argv):
    parser = argparse.ArgumentParser()
    parser.add_argument(
      '--train-files',
      help='GCS file or local paths to training data',
      nargs='+',
      default='gs://cloud-samples-data/ml-engine/census/data/adult.data.csv')
    parser.add_argument(
      '--eval-files',
      help='GCS file or local paths to evaluation data',
      nargs='+',
      default='gs://cloud-samples-data/ml-engine/census/data/adult.test.csv')
    parser.add_argument(
      '--job-dir',
      help='GCS location to write checkpoints and export models',
      default='/tmp/census-estimator')
    parser.add_argument(
      '--num-epochs',
      help="""\
      Maximum number of training data epochs on which to train.
      If both --max-steps and --num-epochs are specified,
      the training job will run for --max-steps or --num-epochs,
      whichever occurs first. If unspecified will run for --max-steps.\
      """,
      type=int)
    parser.add_argument(
      '--train-batch-size',
      help='Batch size for training steps',
      type=int,
      default=40)
    parser.add_argument(
      '--eval-batch-size',
      help='Batch size for evaluation steps',
      type=int,
      default=40)
    parser.add_argument(
      '--embedding-size',
      help='Number of embedding dimensions for categorical columns',
      default=8,
      type=int)
    parser.add_argument(
      '--first-layer-size',
      help='Number of nodes in the first layer of the DNN',
      default=100,
      type=int)
    parser.add_argument(
      '--num-layers',
      help='Number of layers in the DNN',
      default=4,
      type=int)
    parser.add_argument(
      '--scale-factor',
      help='How quickly should the size of the layers in the DNN decay',
      default=0.7,
      type=float)
    parser.add_argument(
      '--train-steps',
      help="""\
      Steps to run the training job for. If --num-epochs is not specified,
      this must be. Otherwise the training job will run indefinitely.""",
      default=100,
      type=int)
    parser.add_argument(
      '--eval-steps',
      help='Number of steps to run evalution for at each checkpoint',
      default=100,
      type=int)
    parser.add_argument(
      '--export-format',
      help='The input format of the exported SavedModel binary',
      choices=['JSON', 'CSV', 'EXAMPLE'],
      default='JSON')
    parser.add_argument(
      '--verbosity',
      choices=['DEBUG', 'ERROR', 'FATAL', 'INFO', 'WARN'],
      default='INFO')
    parser.add_argument(
      '--meta-file',
      help='GCS file or local paths to evaluation data',
      nargs='+',
      default='gs://cloud-samples-data/ml-engine/census/data/adult.test.csv')

    args, _ = parser.parse_known_args()

    # Set python level verbosity
    tf.logging.set_verbosity(args.verbosity)
    # Set C++ Graph Execution level verbosity
    os.environ['TF_CPP_MIN_LOG_LEVEL'] = str(
      tf.logging.__dict__[args.verbosity] / 10)

    # path_to_train_tfrecords_file = os.path.join(FLAGS.data_dir, 'train.tfrecords') #./data/train.tfrecords
    # path_to_val_tfrecords_file = os.path.join(FLAGS.data_dir, 'val.tfrecords') #./data/val.tfrecords
    # path_to_tfrecords_meta_file = os.path.join(FLAGS.data_dir, 'meta.json') #./data/meta.json
    # path_to_train_log_dir = FLAGS.train_logdir #./logs/train
    # path_to_restore_checkpoint_file = FLAGS.restore_checkpoint # None or ./logs/train/latest.ckpt

    path_to_train_tfrecords_file = args.train_files #./data/train.tfrecords
    path_to_val_tfrecords_file = args.eval_files #./data/val.tfrecords
    path_to_tfrecords_meta_file = args.meta_file #./data/meta.json
    path_to_train_log_dir = args.job_dir #./logs/train
    path_to_restore_checkpoint_file = FLAGS.restore_checkpoint # None or ./logs/train/latest.ckpt

    training_options = {
        'batch_size': FLAGS.batch_size,
        'learning_rate': FLAGS.learning_rate,
        'patience': FLAGS.patience,
        'decay_steps': FLAGS.decay_steps,
        'decay_rate': FLAGS.decay_rate
    }

    meta = Meta()
    meta.load(path_to_tfrecords_meta_file)
    num_train_examples = meta.num_train_examples
    num_val_examples = meta.num_val_examples

    _train(path_to_train_tfrecords_file, num_train_examples,
           path_to_val_tfrecords_file, num_val_examples,
           path_to_train_log_dir, path_to_restore_checkpoint_file,
           training_options)


if __name__ == "__main__":

    tf.app.run(main=main)


#  docker /notebooks/dataVolume/workspace/data
# path_to_tfrecords_file = '/notebooks/dataVolume/workspace/data/train.tfrecords'
# path_to_train_log_dir = '/notebooks/dataVolume/workspace/logs/train'
# path_to_val_tfrecords_file = '/notebooks/dataVolume/workspace/data/val.tfrecords'

#  amax
# path_to_train_tfrecords_file = '/home/amax/Documents/wit/data/train.tfrecords'
# path_to_train_log_dir = '/home/amax/Documents/wit/logs/train'
# path_to_val_tfrecords_file = '/home/amax/Documents/wit/data/val.tfrecords'
# path_to_restore_checkpoint_file = '/home/amax/Documents/wit/logs/train/latest.ckpt'
