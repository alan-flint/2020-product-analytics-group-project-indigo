import boto3
import os
import random
import re
import unicodedata
import json


from config import Config
from datetime import datetime
from flask import render_template, redirect, url_for, request, flash, Flask
from flask_login import LoginManager, UserMixin, current_user, login_user, \
    login_required, logout_user
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileRequired
# from flask_bootstrap import Bootstrap
from wtforms import BooleanField, DateField, IntegerField, SelectField, \
    SubmitField, PasswordField, StringField, validators, Form, \
    MultipleFileField
from wtforms.validators import DataRequired
from werkzeug.security import check_password_hash, generate_password_hash


ALLOWED_EXTENSIONS = {'midi', 'mid'}

on_dev = True

# Initialization
# Create an application instance which handles all requests.
application = Flask(__name__)
application.secret_key = os.urandom(24)
application.config.from_object(Config)

db = SQLAlchemy(application)
db.create_all()
db.session.commit()

# bootstrap = Bootstrap(application)

# login_manager needs to be initiated before running the app
login_manager = LoginManager()
login_manager.init_app(application)


class UploadFileForm(FlaskForm):
    """Class for uploading file when submitted"""
    file_selector = FileField('File', validators=[FileRequired()])
    submit = SubmitField('Submit')


class UploadMultipleForm(FlaskForm):
    """
    Class for uploading multiple files. Note that the FileAllowed validator
    does not work for MultipleFileField.
    """
    files = MultipleFileField('Files')
    submit = SubmitField('Submit')


class RegistrationForm(FlaskForm):
    """Class for register a new user."""
    username = StringField('Username', [validators.Length(min=4, max=25)])
    email = StringField('Email Address', [validators.Length(min=6, max=35)])
    password = PasswordField('New Password', [
        validators.DataRequired(),
        validators.EqualTo('confirm', message='Passwords must match')
    ])
    confirm = PasswordField('Repeat Password')
    accept_tos = BooleanField('I accept the TOS', [validators.DataRequired()])
    submit = SubmitField('Submit')


class LogInForm(FlaskForm):
    """Class for login form"""
    username = StringField('Username:', validators=[DataRequired()])
    password = PasswordField('Password:', validators=[DataRequired()])
    submit = SubmitField('Login')


class Customer(db.Model, UserMixin):
    """Class for user object"""
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)

    def __init__(self, username, email, password):
        self.username = username
        self.email = email
        self.set_password(password)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Files(db.Model, UserMixin):
    """File class with file and user properties for database"""

    id = db.Column(db.Integer, primary_key=True)
    user_name = db.Column(db.String(80), nullable=False)
    orig_filename = db.Column(db.String(120), nullable=False)
    file_type = db.Column(db.String(120), nullable=False)  # mid or mp3 etc
    # gan, user_upload, rnn, vae, etc
    model_used = db.Column(db.String(120), nullable=False)
    our_filename = db.Column(db.String(80), unique=True, nullable=False)
    file_upload_timestamp = db.Column(db.String(120), nullable=False)

    def __init__(self, user_name, orig_filename, file_type, model_used,
                 our_filename, file_upload_timestamp):
        self.user_name = user_name
        self.orig_filename = orig_filename
        self.file_type = file_type
        self.model_used = model_used
        self.our_filename = our_filename
        self.file_upload_timestamp = file_upload_timestamp


db.create_all()
db.session.commit()


@login_manager.user_loader
def load_user(id):
    """
    This callback is used to reload the user object
    from the user ID stored in the session.
    """
    return Customer.query.get(int(id))


def allowed_file(filename):
    """Checks if file is of allowed type"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@application.route('/index')
@application.route('/')
def index():
    """Index Page : Renders index.html with author names."""
    if current_user.is_authenticated:
        username = current_user.username
    else:
        username = None
    return render_template('index.html', username=username,
                           authenticated=current_user.is_authenticated)


@application.route('/register',  methods=['GET', 'POST'])
def register():
    """Register function that writes new user to SQLite DB"""
    registration_form = RegistrationForm()
    if registration_form.validate_on_submit():
        username = registration_form.username.data
        password = registration_form.password.data
        email = registration_form.email.data

        user_count = Customer.query.filter_by(username=username).count() \
            + Customer.query.filter_by(email=email).count()
        if user_count > 0:
            flash('Username or email already exists')
        else:
            user = Customer(username, email, password)
            db.session.add(user)
            db.session.commit()
            return redirect(url_for('login'))
    return render_template('register.html', form=registration_form)


@application.route('/login', methods=['GET', 'POST'])
def login():
    """Login function that takes in username and password."""
    login_form = LogInForm()
    if login_form.validate_on_submit():
        username = login_form.username.data
        password = login_form.password.data
        # Look for it in the database.
        user = Customer.query.filter_by(username=username).first()

        # Login and validate the user.
        if user is not None and user.check_password(password):
            login_user(user)
            return redirect(url_for('profile', username=username))
        else:
            flash('Incorrect Password')

    return render_template('login.html', form=login_form)


@application.route('/logout')
@login_required
def logout():
    """Logout user"""
    logout_user()
    return redirect(url_for('index'))


@application.route('/profile/<username>', methods=['GET', 'POST'])
@login_required
def profile(username):
    uploads = Files.query.filter_by(user_name=username).all()
    other_users = Customer.query.all()
    other_users = [o.username for o in other_users]
    other_users.remove(current_user.username)
    other_users.remove('test')
    random.shuffle(other_users)

    ##############
    if on_dev:
        s3 = boto3.resource('s3')  # comment out when on local
    # LOCAL
    else:
        # insert your profile name
        session = boto3.Session(profile_name='msds603')
        s3 = session.resource('s3')

    try:
        objects = [s3.Object('midi-file-upload', u.orig_filename)
                   for u in uploads]

        # binary_body = object.get()['Body'].read()
        # return render_template('test_playback.html', midi_binary=binary_body)

        # make directory and save files there
        file_dir_path = './static/tmp'

        if not os.path.exists(file_dir_path):
            os.mkdir(file_dir_path)

        for o in range(len(objects)):
            objects[o].download_file(f'./static/tmp/'
                                     f'{uploads[o].orig_filename}.mid')

        user_file = True
    except Exception as e:
        # Flag used in template to direct file to be
        # loaded from tmp or samples directory
        user_file = False

    return render_template('profile.html', uploads=uploads,
                           username=username, objects=objects,
                           other_users=other_users[:3])


@application.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    """
    Upload a file from a client machine to
    s3 and file properties to Database
    """
    file = UploadFileForm()  # file : UploadFileForm class instance
    uploads = Files.query.filter_by(user_name=current_user.username).all()

    # Check if it is a POST request and if it is valid.
    if file.validate_on_submit():
        f = file.file_selector.data  # f : Data of FileField
        filename = f.filename
        # filename : filename of FileField
        if not allowed_file(filename):
            flash('Incorrect File Type')
            return redirect(url_for('upload'))

        # make directory and save files there
        cwd = os.getcwd()

        file_dir_path = os.path.join(cwd, 'files')

        if not os.path.exists(file_dir_path):
            os.mkdir(file_dir_path)

        file_path = os.path.join(file_dir_path, filename)

        f.save(file_path)

        user_name = current_user.username
        orig_filename = filename.rsplit('.', 1)[0]
        file_type = filename.rsplit('.', 1)[1]
        model_used = 'user_upload'

        # get num of files user has uploaded thus far
        num_user_files = Files.query.filter_by(user_name=user_name).count()
        our_filename = f'{user_name}_{num_user_files}'
        file_upload_timestamp = datetime.now()

        # check for duplicates file
        user_file_list = db.session.query(Files.orig_filename)\
            .filter(Files.user_name == user_name).all()
        user_file_list = [elem[0] for elem in user_file_list]

        if orig_filename in user_file_list:
            flash('You have already uploaded a file with this name, \
                  please upload a new file or rename this one to upload.')
            return redirect(url_for('upload'))

        file = Files(user_name, orig_filename, file_type,
                     model_used, our_filename, file_upload_timestamp)
        db.session.add(file)
        db.session.commit()

        # TAKES CARE OF DEV OR local
        if on_dev:
            s3 = boto3.resource('s3')
            s3.meta.client.upload_file(file_path, 'midi-file-upload',
                                       our_filename)

        # USE FOR REMOTE - msds603 is my alias in ./aws credentials file using
        # secret key from iam on jacobs account
        else:
            session = boto3.Session(profile_name='msds603')
            dev_s3_client = session.resource('s3')
            dev_s3_client.meta.client.upload_file(file_path,
                                                  'midi-file-upload',
                                                  our_filename)

        if os.path.exists(file_dir_path):
            os.system(f"rm -rf {file_dir_path}")
        # Redirect to /profile/<username> page.
        return redirect(url_for('profile', username=current_user.username))

    return render_template('upload.html', form=file, uploads=uploads,
                           username=current_user.username)


@application.route('/about', methods=['GET', 'POST'])
def about():
    """Load About page"""
    if current_user.is_authenticated:
        username = current_user.username
    else:
        username = None
    return render_template('about.html', username=username,
                           authenticated=current_user.is_authenticated)


@application.route('/buy', methods=['GET', 'POST'])
def buy():
    """ Return page with information on purchasing our product
    """
    if current_user.is_authenticated:
        username = current_user.username
    else:
        username = None
    return render_template('buy.html', username=username,
                           authenticated=current_user.is_authenticated)


@application.route('/drums/<filename>', methods=['GET', 'POST'])
@login_required
def drums(filename):
    """
    Render drums page with uploaded or selected files from drums upload page
    """
    if on_dev:
        s3 = boto3.resource('s3')  # comment out when on local
    # LOCAL
    else:
        # insert your profile name
        session = boto3.Session(profile_name='msds603')
        s3 = session.resource('s3')

    try:
        object = s3.Object('midi-file-upload', filename)

        # binary_body = object.get()['Body'].read()
        # return render_template('test_playback.html', midi_binary=binary_body)

        # make directory and save files there
        file_dir_path = './static/tmp'

        if not os.path.exists(file_dir_path):
            os.mkdir(file_dir_path)
        # Determine if file from model output (noteSequence object)
        # or existing user-upload (midi file)
        file_type = db.session.query(Files.model_used).\
            filter(Files.our_filename == filename).all()[0][0]
        print(file_type)
        data = None
        # If a model file, then need to parse json note sequence object,
        # not midi file
        if file_type in ['rnn', 'vae']:
            model_file = True
            object.download_file(f'./static/tmp/{filename}.json')
            with open(f'./static/tmp/{filename}.json', 'r') as f:
                data = f.read()
        else:
            model_file = False
            object.download_file(f'./static/tmp/{filename}.mid')

        user_file = True
    except Exception as e:
        # Flag used in template to direct file to be
        # loaded from tmp or samples directory
        user_file = False
        model_file = False
        data = None

    finally:
        return render_template('drums.html', midi_file=filename + '.mid',
                               user_file=user_file, model_file=model_file,
                               data=data, username=current_user.username)


@application.errorhandler(401)
def re_route(e):
    """ Handle 401 errors and redirect non-logged in users to login page.
    """
    return redirect(url_for('login'))


@application.route('/drums-upload', methods=['GET', 'POST'])
@login_required
def drums_upload():
    """
    Upload a file from a client machine to
    s3 and file properties to Database
    """
    file = UploadFileForm()  # file : UploadFileForm class instance
    uploads = Files.query.filter_by(user_name=current_user.username).all()

    # Check if it is a POST request and if it is valid.
    if file.validate_on_submit():
        f = file.file_selector.data  # f : Data of FileField
        filename = f.filename
        # filename : filename of FileField
        if not allowed_file(filename):
            flash('Incorrect File Type: Please upload a MIDI file')
            return redirect('drums-upload')
        # make directory and save files there
        cwd = os.getcwd()

        file_dir_path = os.path.join(cwd, 'files')

        if not os.path.exists(file_dir_path):
            os.mkdir(file_dir_path)

        file_path = os.path.join(file_dir_path, filename)

        f.save(file_path)

        user_name = current_user.username
        orig_filename = filename.rsplit('.', 1)[0]
        file_type = filename.rsplit('.', 1)[1]
        model_used = 'user_upload'

        # get num of files user has uploaded thus far
        num_user_files = Files.query.filter_by(user_name=user_name).count()
        our_filename = f'{user_name}_{num_user_files}'
        file_upload_timestamp = datetime.now()

        # check for duplicates file
        user_file_list = db.session.query(Files.orig_filename).\
            filter(Files.user_name == user_name).all()
        user_file_list = [elem[0] for elem in user_file_list]

        if orig_filename in user_file_list:
            flash(
                'You have already uploaded a file with this name, '
                'please upload a new file or rename this one to upload.')
            return redirect('drums-upload')

        file = Files(user_name, orig_filename, file_type,
                     model_used, our_filename, file_upload_timestamp)
        db.session.add(file)
        db.session.commit()

        # TAKES CARE OF DEV OR local
        if on_dev:
            s3 = boto3.resource('s3')
            s3.meta.client.upload_file(file_path, 'midi-file-upload',
                                       our_filename)

        # USE FOR REMOTE - msds603 is my alias in ./aws credentials file using
        # secret key from iam on jacobs account
        else:
            session = boto3.Session(profile_name='msds603')
            dev_s3_client = session.resource('s3')
            dev_s3_client.meta.client.upload_file(file_path,
                                                  'midi-file-upload',
                                                  our_filename)

        if os.path.exists(file_dir_path):
            os.system(f"rm -rf {file_dir_path}")

        return redirect(f'/drums/{our_filename}')  # Redirect to drums page.

    return render_template('drums-upload.html', form=file, uploads=uploads,
                           username=current_user.username)


@application.route('/vae-upload', methods=['GET', 'POST'])
@login_required
def vae_upload():
    """ Page to upload two files for use in music interpolation
    using the MusicVAE
    """
    file = UploadMultipleForm()

    if file.validate_on_submit():
        ls_files = request.files.getlist('midi_files')
        if len(ls_files) == 2:
            f1, f2 = ls_files[0], ls_files[1]
            filename1, filename2 = f1.filename, f2.filename

            if (not allowed_file(filename1)) or (not allowed_file(filename1)):
                flash('Incorrect File Type: Please upload MIDI files - .mid '
                      'or .midi extensions')
                return redirect('vae-upload')
            else:
                # write locally. Will be deleted later.
                cwd = os.getcwd()
                file_dir_path = os.path.join(cwd, 'files')
                if not os.path.exists(file_dir_path):
                    os.mkdir(file_dir_path)
                file_path1 = os.path.join(file_dir_path, filename1)
                file_path2 = os.path.join(file_dir_path, filename2)
                f1.save(file_path1)
                f2.save(file_path2)

                model_used = 'user_upload'
                user_name = current_user.username

                orig_filename1 = filename1.rsplit('.', 1)[0]
                file_type1 = filename1.rsplit('.', 1)[1]
                num_user_files1 = Files.query.filter_by(user_name=user_name).\
                    count()
                our_filename1 = f'{user_name}_{num_user_files1}'
                file_upload_timestamp1 = datetime.now()
                file1 = Files(user_name, orig_filename1, file_type1,
                              model_used, our_filename1,
                              file_upload_timestamp1)
                db.session.add(file1)

                orig_filename2 = filename2.rsplit('.', 1)[0]
                file_type2 = filename2.rsplit('.', 1)[1]
                num_user_files2 = Files.query.filter_by(user_name=user_name).\
                    count()
                our_filename2 = f'{user_name}_{num_user_files2}'
                file_upload_timestamp2 = datetime.now()
                file2 = Files(user_name, orig_filename2, file_type2,
                              model_used, our_filename2,
                              file_upload_timestamp2)
                db.session.add(file2)

                db.session.commit()

                if on_dev:
                    s3 = boto3.resource('s3')
                else:
                    s3 = boto3.Session(profile_name='msds603').resource('s3')

                s3.meta.client.upload_file(file_path1, 'midi-file-upload',
                                           our_filename1)
                s3.meta.client.upload_file(file_path2, 'midi-file-upload',
                                           our_filename2)

                # remove the locally written files
                if os.path.exists(file_dir_path):
                    os.system(f"rm -rf {file_dir_path}")

                # redirect to vae url with file arguments
                return redirect(url_for('vae', filename1=our_filename1,
                                        filename2=our_filename2))
        else:
            flash('Please upload exactly 2 MIDI files')
            return redirect('vae-upload')

    return render_template('vae-upload.html',
                           form=file, username=current_user.username)


# @application.route('/vae/<filename1>/<filename2>',
# methods=['GET', 'POST']) # not working
@application.route('/vae', methods=['GET', 'POST'])
@login_required
def vae():
    """Interpolate between 2 files using MusicVAE using the two uploaded files
    """

    filename1 = request.args.get('filename1')
    filename2 = request.args.get('filename2')

    if on_dev:
        s3 = boto3.resource('s3')  # comment out when on local
    # LOCAL
    else:
        # insert your profile name
        session = boto3.Session(profile_name='msds603')
        s3 = session.resource('s3')

    object1 = s3.Object('midi-file-upload', filename1)
    object2 = s3.Object('midi-file-upload', filename2)

    # make directory and save files there
    file_dir_path = './static/tmp'

    if not os.path.exists(file_dir_path):
        os.mkdir(file_dir_path)

    object1.download_file(f'./static/tmp/{filename1}.mid')
    object2.download_file(f'./static/tmp/{filename2}.mid')

    return render_template('vae.html',
                           midi_file1=filename1 + '.mid',
                           midi_file2=filename2 + '.mid', 
                           username=current_user.username)


@application.route('/save', methods=['GET', 'POST'])
def save():
    """

    """
    try:
        jsonData = request.get_json()
        print(jsonData)
        model_used = jsonData['model']
        newFilename = slugify(jsonData["output_filename"])
        noteSequence = jsonData['noteSequence']  # Output should be a dict
        fileData = json.dumps(noteSequence)

        file_path = f'static/tmp/{newFilename}.json'
        with open(file_path, 'w') as f:
            f.write(fileData)

        user_name = current_user.username
        orig_filename = newFilename
        print(orig_filename)

        # get num of files user has uploaded thus far
        num_user_files = Files.query.filter_by(user_name=user_name).count()
        our_filename = f'{user_name}_{num_user_files}_{model_used}'
        file_upload_timestamp = datetime.now()

        # check for duplicates file
        user_file_list = db.session.query(Files.orig_filename). \
            filter(Files.user_name == user_name).all()
        user_file_list = [elem[0] for elem in user_file_list]

        if orig_filename in user_file_list:
            return(
                'You have already uploaded a file with this name, '
                'please rename this one to save.')

        file = Files(user_name, orig_filename, 'json',
                     model_used, our_filename, file_upload_timestamp)
        db.session.add(file)
        db.session.commit()

        # TAKES CARE OF DEV OR local
        if on_dev:
            s3 = boto3.resource('s3')
            s3.meta.client.upload_file(file_path, 'midi-file-upload',
                                       our_filename)

        # USE FOR REMOTE - msds603 is my alias in ./aws credentials file using
        # secret key from iam on jacobs account
        else:
            session = boto3.Session(profile_name='msds603')
            dev_s3_client = session.resource('s3')
            dev_s3_client.meta.client.upload_file(file_path,
                                                  'midi-file-upload',
                                                  our_filename)

        return "File saved!"

    except Exception as e:
        return f"Error occurred, try again: \n {e}"


def slugify(value, allow_unicode=False):
    """
    Convert to ASCII if 'allow_unicode' is False. Convert spaces to hyphens.
    Remove characters that aren't alphanumerics, underscores, or hyphens.
    Convert to lowercase. Also strip leading and trailing whitespace.
    """
    value = str(value)
    if allow_unicode:
        value = unicodedata.normalize('NFKC', value)
    else:
        value = unicodedata.normalize('NFKD', value).\
            encode('ascii', 'ignore').decode('ascii')
    value = re.sub(r'[^\w\s-]', '', value.lower()).strip()
    return re.sub(r'[-\s]+', '-', value)


if __name__ == '__main__':
    application.jinja_env.auto_reload = True
    application.config['TEMPLATES_AUTO_RELOAD'] = True
    application.debug = True
    application.run()
