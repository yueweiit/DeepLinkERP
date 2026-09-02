import CSVRawDataPreview from './CSVRawDataPreview'
import StatementDetails from './StatementDetails'
import { GetStatementDetailsResponse } from '../import_utils'

const CSVImport = ({ data, mutate }: { data: { message: GetStatementDetailsResponse }, mutate: () => void }) => {

    return (
        <div className="w-full min-w-0 flex">
            <div className="w-[50%] min-w-0 p-4 h-[calc(100vh-72px)] overflow-auto">
                <StatementDetails data={data.message} />
            </div>
            <div className="w-[50%] min-w-0 border-s border-t pe-1 ps-0 border-outline-gray-2 h-[calc(100vh-72px)] overflow-auto">
                <CSVRawDataPreview data={data.message} mutate={mutate} />
            </div>
        </div>
    )
}

export default CSVImport
