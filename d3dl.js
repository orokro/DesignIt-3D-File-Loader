/*
	d3dl.js
	-------

	DesignIt-3D Loader.
*/

// load list of headers for parsing the file
const {vvrHeaders, vvrNoDataHeaders} = require('./VVRHeaders.js');

// use file system so we can load the binary file
const fs = require('fs');

// get the file to load,
// for now we'll also always default to "JUSTCUBE.VVR" for debugging
const fileToLoad = (process.argv[2] || 'JUSTCUBE.VVR');

// load the file's binary
const fileBuffer = fs.readFileSync(`./${fileToLoad}`);

// to start, we'll loop over the entire buffer, looking for combinations of four uppercase letters
// that match one of our vvrHeaders.
// then, we'll continue recording binary until we hit another header or EOF

// make buffer regular array
const binArray = [];
for (x of fileBuffer)
	binArray.push(x);

// make a custom object with our custom FILE header to be the top-level
// object for the recursive function we're gonna process. 
const fileData = {
	header: "FILE",
	len: binArray.length,
	children: [],
	data: binArray
}

function objectParse(objData){

	/*
		Right so we can assume the object passed in looks something like:
		{
			header: "AAAA",
			len: <Number>,
			children: [],
			data: [...]
		}

		Where:
			- header - is the one of the four digit codes we discovered in the VVR files.
			- len - is the length in bytes that comes after every header except VMDL
			- children - is an empty array initially that's populated by objects this fn finds
			- data - is the binary that matches len when the object itself was parsed.

		So, we want to loop over the data we're given looking for four-letter codes.
		After every four letter code, comes four bytes specifying the number of bytes
		for that object.

		We can assume that, if the bytes include other objects, then a hierarchy forms

		Also note, that the first header always seems to be FORM and always seems to specify
		the entire file length in bytes. Let's hope that assumption holds true.
	*/

	// handy function we'll use to read four bytes as an integer
	function readFourToInt(data){
		return  (Math.pow(256, 3) * data.shift()) +
				(Math.pow(256, 2) * data.shift()) +
				(Math.pow(256, 1) * data.shift()) +
				(Math.pow(256, 0) * data.shift());
	}

	// wasteful function to copy a fixed amount of bytes into a new array
	function grabBytes(data, count){
		const returnData = [];
		for(let i=0; i<count; i++)
			if(data.length>0)
				returnData.push(data.shift());

		return returnData;
	}

	// for sanity, clone data
	const data = [...objData.data];

	// we'll store data that we didn't use in this "left-overs" array
	const unusedData = [];

	// buffer of last four while we look for our keywords
	let lastFour = [];

	// we will loop until we run out of data or exit the loop early
	while(data.length>0){

		// pop first byte in array
		const b = data.shift();

		// add to our last four & unshift the front if we're over 4 total
		lastFour.push(b);
		while(lastFour.length>4)
			unusedData.push(lastFour.shift());	

		// get the last-four as a single 4-digit string, and then check if
		// it's in our list of recognized header-codes
		const lastFourStr = lastFour.map(b => String.fromCharCode(b)).join('');
		if(vvrHeaders.includes(lastFourStr) == true){

			// flush last four
			lastFour = [];

			// check if the next four are ALSO a header
			// if so, we can assume this header is empty, so we'll push it
			// in the children as an empty header
			const nextFourStr= [data[0], data[1], data[2], data[3]].map(b => String.fromCharCode(b)).join('');
			if(vvrHeaders.includes(nextFourStr) == true){
				objData.children.push({
					header: lastFourStr,
					len: 0,
					children: [],
					data: []
				});
				
				// skip rest
				continue;
			}

			// save as header
			const header = lastFourStr;

			// all other headers seem to immediately use the next four bytes
			// as a 32 bit integer, being the length of the object in bytes
			const len = readFourToInt(data);

			// get that many bytes from our data
			const newDataBytes = grabBytes(data, len);

			// make new data object with the data we've collected
			const newChildObject = {
				header: header,
				len: len,
				children: [],
				data: newDataBytes
			};

			// add this new object the current objects list of children
			objData.children.push(newChildObject);

			// recursively parse this object also!
			objectParse(newChildObject);
		}

	}// wend

	// if we ran out of data, save whatever is left over from last four
	while(lastFour.length>0)
		unusedData.push(lastFour.shift());	

	// replace the objects data with just the unused data
	objData.data = unusedData;
	
}


objectParse(fileData);
  
// recursively print data
function printData(object, depth, tabSize){

	// compute depth space indentation
	const indent = Array(depth+1).join(Array(tabSize).join("\t"));

	// print our objects header & it's length on one line, and it's data on the next
	console.log(indent + `•${object.header} (${object.len})`);

	// if this object has raw data, print that
	const dataLine = object.data.join(', ');
	if(dataLine.length>0)
		console.log(indent + ' ' + dataLine);

	// line to make things nice
	console.log(indent);

	// do same for all it's children
	for(let i=0; i<object.children.length; i++){
		const child = object.children[i];
		printData(child, depth+1, tabSize);
	}// next i
}

printData(fileData, 0, 3);
